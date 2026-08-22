"""Núcleo del runner de video: comando ffmpeg + supervisión de la TRANSMISIÓN.

El ffmpeg a mano del banco moría con Broken pipe al reiniciar MediaMTX y había
que relanzarlo a mano; además apuntaba a /dev/videoN, que baila con el USB
(la clase de incidente de ADR-018). Este módulo lo reemplaza con:

- `comando_ffmpeg()`: función pura que arma el argv exacto validado en el banco
  (x264 ultrafast/zerolatency, CBR, RTSP por TCP), parametrizado.
- `SupervisorTransmision`: lanza el ffmpeg, vigila la transmisión y lo relanza
  con backoff progresivo cuando sale O cuando se ESTANCA.

Por qué se vigila el progreso y no solo la vida del proceso (ADR-020): hay dos
cuelgues reales en los que ffmpeg NO sale — el demuxer v4l2 bloqueado en una
cámara UVC atascada, y el send() TCP bloqueado en una caída silenciosa del
camino de red (half-open: el kernel tarda ~15 min en rendirse). En ambos, el
dashboard mostraría un frame congelado que PARECE video en vivo: el equivalente
en video de servir un dato viejo como actual. Con `-progress pipe:1` ffmpeg
reporta su avance ~2 veces/s; si el reporte se detiene, se derriba y relanza.

Identidad del dispositivo (extiende ADR-018 al relanzamiento automático):
- La clasificación identidad/ruta/índice replica las reglas de
  `ocr.fuente.FuenteCapturadora` (réplica deliberada: cero ediciones en `ocr/`;
  `ocr.dispositivos` se usa SOLO por importación).
- En la primera resolución se FIJA (pin) la identidad física del dispositivo;
  cada relanzamiento debe resolver AL MISMO dispositivo. Con cámaras con serial
  el pin es el by-id (la cámara puede cambiar de puerto y se la sigue); con
  webcams sin serial (p. ej. la Jieli del banco, by-id sin serial) el pin es el
  by-path: el PUERTO es la única ancla física, y dos webcams idénticas
  intercambiadas serían indistinguibles de otro modo.
- Identidad que resuelve a OTRO dispositivo físico -> no se lanza: se espera al
  original con backoff. Nodo literal que ahora es OTRA cámara -> fatal ruidoso:
  relanzar transmitiría la cama equivocada.

Cierre limpio: sin handler propio de SIGINT — KeyboardInterrupt emerge de
wait()/sleep (PEP 475) y el apagado (terminate -> gracia -> kill) corre en
except/finally, el patrón de `ocr.publicar.correr`. El CLI mapea SIGTERM a la
misma excepción (systemd futuro). En Linux el ffmpeg se lanza con
PR_SET_PDEATHSIG: si el runner muere sin limpiar, ffmpeg muere con él y no
retiene /dev/videoN (EBUSY).
"""

import os
import re
import subprocess
import sys
import threading
import time

# Tiempos de la supervisión (segundos)
ESPERA_INICIAL_S = 1        # primer reintento tras un fallo
ESPERA_MAX_S = 30           # tope del backoff (cámara ausente: 1 intento/30 s)
UMBRAL_SANO_S = 30          # transmisión SANA >= esto -> el backoff se resetea
GRACIA_TERMINATE_S = 3      # de terminate a kill en el apagado
ESPERA_KILL_S = 10          # tope del wait tras SIGKILL (D-state: ni kill mata)
TIMEOUT_PROGRESO_S = 10.0   # sin progreso de ffmpeg -> transmisión estancada
_TICK_ESPERA_S = 1          # granularidad del poll wait() para el watchdog

# Seriales de fábrica que NO identifican la unidad (iSerial placeholder,
# idéntico en todas las unidades del modelo — común en UVC baratas): traen
# dígitos, así que la heurística de "serial utilizable" los dejaría pasar y el
# pin by-id no distinguiría dos webcams intercambiadas.
_SERIALES_PLACEHOLDER = frozenset({
    "0000", "0001", "00000000", "1234", "12345", "123456", "01.00.00",
    "20200101", "20210101",
})


class TransmisionFatal(RuntimeError):
    """Fallo que reintentar no arregla (entorno roto, fuente cambiada):
    el runner debe salir ruidosamente pidiendo intervención, no perseverar."""


def comando_ffmpeg(nodo, cama_id, servidor, puerto, ancho, alto, fps,
                   bitrate, formato_entrada="mjpeg", progreso=True):
    """Argv del ffmpeg de baja latencia validado en el banco (función pura).

    - `-g fps` = 1 keyframe/s: latencia de incorporación ~1 s para el
      espectador WebRTC.
    - CBR aproximado con la proporción validada (2M/2M/1M): maxrate = bitrate,
      bufsize = bitrate/2.
    - `-input_format mjpeg` por defecto: capturar YUYV crudo por USB corrompe
      buffers a 640x480/30 (lección del simulador). `formato_entrada="none"`
      lo omite para cámaras sin MJPG.
    - `-rtsp_transport tcp`: lo validado; UDP pierde paquetes en la tailnet.
    - `-progress pipe:1` alimenta el watchdog de estancamiento; se omite en
      `--una-vez` (nadie drenaría el pipe y ffmpeg se bloquearía escribiendo).
    """
    cmd = ["ffmpeg", "-loglevel", "warning"]
    if progreso:
        cmd += ["-progress", "pipe:1"]
    cmd += ["-f", "v4l2"]
    if formato_entrada and formato_entrada.lower() != "none":
        cmd += ["-input_format", formato_entrada]
    cmd += [
        "-video_size", f"{ancho}x{alto}",
        "-framerate", str(fps),
        "-i", nodo,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-g", str(fps),
        "-b:v", bitrate,
        "-maxrate", bitrate,
        "-bufsize", mitad_de_bitrate(bitrate),
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        f"rtsp://{servidor}:{puerto}/{cama_id}",
    ]
    return cmd


def mitad_de_bitrate(bitrate):
    """"2M" -> "1M", "800k" -> "400k", "3M" -> "1500k" (bufsize = bitrate/2).

    Redondea a k (no trunca: "5k" -> "3k") y con piso de "1k": un bufsize de
    0 desactivaría el VBV de x264 — exactamente el tope CBR que la pareja
    maxrate/bufsize existe para imponer.
    """
    m = re.fullmatch(r"(\d+)([kM])", bitrate, flags=re.ASCII)
    if not m:
        raise ValueError(
            f"Bitrate {bitrate!r} inválido: se espera número + sufijo k o M "
            f"(p. ej. 2M, 800k)."
        )
    bits = int(m.group(1)) * (1_000_000 if m.group(2) == "M" else 1_000)
    kilos = max(1, (bits // 2 + 500) // 1_000)
    if kilos % 1_000 == 0:
        return f"{kilos // 1_000}M"
    return f"{kilos}k"


def clasificar_dispositivo(dispositivo):
    """('literal', ruta) o ('identidad', aguja).

    Réplica deliberada de las reglas de `ocr.fuente.FuenteCapturadora`
    (ADR-018), sin editar `ocr/`: strip antes de clasificar; dígitos <= 3 =
    índice V4L2 literal (ningún /dev/videoN real pasa de ahí; un dígito-largo
    como un serial es IDENTIDAD); ruta que empieza con '/' = literal; el resto
    es identidad estable y pasa por `ocr.dispositivos.resolver()`. A diferencia
    de FuenteCapturadora (cv2 acepta índices), ffmpeg necesita RUTA: el índice
    se traduce a /dev/videoN.
    """
    d = dispositivo.strip() if isinstance(dispositivo, str) else dispositivo
    if isinstance(d, int):
        return ("literal", f"/dev/video{d}")
    if d.isdigit() and len(d) <= 3:
        return ("literal", f"/dev/video{int(d)}")
    if d.startswith("/"):
        return ("literal", d)
    if not d:
        raise TransmisionFatal("Identificador de cámara vacío.")
    return ("identidad", d)


def pin_de(dispositivo_captura, companeros=()):
    """El ancla física de un DispositivoCaptura: ('by-id'|'by-path'|'nombre', valor).

    Política (ADR-020, fijada con la sonda del banco del 21-ago-2026):
    - by-id CON serial utilizable (el token final trae dígitos, no es un
      placeholder conocido, y ningún OTRO dispositivo enumerado comparte el
      by-id) -> pin por by-id: la cámara puede cambiar de puerto USB y se la
      sigue, porque el serial identifica la UNIDAD.
    - by-id SIN serial (la webcam Jieli del banco: by-id
      usb-Jieli_Technology_USB_Composite_Device, token final "Device" sin
      dígitos = placeholder), serial placeholder de fábrica ("0001",
      "01.00.00"...), o by-id COMPARTIDO con otra unidad enumerada -> pin por
      by-path: el PUERTO es la única ancla, y dos webcams idénticas
      intercambiadas compartirían by-id. Requiere etiquetado físico de
      puertos (runbook).
    - Heurística conservadora a propósito: ante la duda se ancla al puerto,
      que es MÁS estricto, nunca menos seguro. Residual documentado en el
      ADR: un placeholder con dígitos fuera de la lista, con una sola unidad
      enchufada al fijar el pin, no es detectable — por eso el runbook manda
      elegir webcams sin serial por by-path (la aguja misma ancla el puerto).

    `companeros`: el resto de la enumeración, si está disponible, para
    detectar by-id compartidos.
    """
    d = dispositivo_captura
    serial_utilizable = (
        d.by_id
        and any(c.isdigit() for c in d.serial)
        and d.serial.lower() not in _SERIALES_PLACEHOLDER
        and not any(o.by_id == d.by_id for o in companeros if o is not d)
    )
    if serial_utilizable:
        return ("by-id", d.by_id)
    if d.by_path:
        return ("by-path", d.by_path)
    if d.by_id:
        return ("by-id", d.by_id)
    return ("nombre", d.nombre)


def coincide_pin(pin, dispositivo_captura):
    """¿El dispositivo tiene el MISMO valor en el atributo que ancla el pin?

    La verificación compara el atributo fijado, no recalcula la política:
    si una segunda unidad idéntica aparece después de fijar el pin, la
    original debe seguir coincidiendo (recalcular la política la degradaría
    a by-path y el runner dejaría de reconocer a su propia cámara).
    """
    clave, valor = pin
    actual = {
        "by-id": dispositivo_captura.by_id,
        "by-path": dispositivo_captura.by_path,
        "nombre": dispositivo_captura.nombre,
    }[clave]
    return actual == valor


def _resolver_identidad(aguja):
    """Seam por defecto: ocr.dispositivos.resolver (import perezoso)."""
    from ocr.dispositivos import resolver
    return resolver(aguja)


def _dispositivo_de_nodo(nodo):
    """DispositivoCaptura dueño de un nodo, o None si no se puede determinar.

    Compara por realpath: un literal symlink (/dev/v4l/by-id/... o by-path/...)
    debe encontrar su dispositivo igual que la ruta /dev/videoN real.
    """
    try:
        from ocr.dispositivos import listar_dispositivos
        dispositivos = listar_dispositivos()
    except (RuntimeError, OSError):
        return None
    real = os.path.realpath(nodo)
    for d in dispositivos:
        if any(os.path.realpath(n) == real for n, _ in d.nodos):
            return d
    return None


def _listar_disponibles():
    """Seam: la enumeración completa (para detectar by-id compartidos), o None."""
    try:
        from ocr.dispositivos import listar_dispositivos
        return listar_dispositivos()
    except (RuntimeError, OSError):
        return None


def _preexec_pdeathsig():
    """En el hijo, antes del exec: morir con SIGTERM si el padre muere.

    Garantiza que un runner muerto sin limpiar no deje un ffmpeg huérfano
    reteniendo /dev/videoN (EBUSY). Best-effort: mejor lanzar sin la garantía
    que no lanzar. Nota: preexec_fn exige lanzar desde el hilo principal — el
    hilo lector de progreso solo LEE, nunca lanza.
    """
    try:
        import ctypes
        import signal
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass


def _lanzar_ffmpeg(argv, capturar_progreso):
    """Seam por defecto: Popen del ffmpeg real.

    stdout se captura SOLO cuando hay watchdog que lo drene (-progress escribe
    ahí; sin drenaje ffmpeg se bloquearía al llenarse el pipe). stderr queda
    heredado: los warnings del encoder van a la consola del operador.
    """
    extra = {}
    if sys.platform.startswith("linux"):
        extra["preexec_fn"] = _preexec_pdeathsig
    return subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capturar_progreso else None,
        **extra,
    )


class SupervisorTransmision:
    """Lanza y vigila el ffmpeg de UNA cama; relanza con backoff si cae o se
    estanca. Ver el docstring del módulo para el porqué de cada pieza.

    Los colaboradores externos son costuras inyectables para los tests
    (`lanzar`, `resolver`, `identidad_de`, `dormir`, `reloj`): ningún test
    lanza ffmpeg real ni toca V4L2.
    """

    def __init__(self, dispositivo, cama_id, servidor, puerto, ancho, alto,
                 fps, bitrate, formato_entrada="mjpeg",
                 timeout_progreso=TIMEOUT_PROGRESO_S,
                 lanzar=_lanzar_ffmpeg, resolver=_resolver_identidad,
                 identidad_de=_dispositivo_de_nodo, listar=_listar_disponibles,
                 dormir=time.sleep, reloj=time.monotonic):
        self._clase, self._valor = clasificar_dispositivo(dispositivo)
        self._dispositivo_pedido = dispositivo
        self._cama_id = cama_id
        self._servidor = servidor
        self._puerto = puerto
        self._ancho = ancho
        self._alto = alto
        self._fps = fps
        self._bitrate = bitrate
        self._formato_entrada = formato_entrada
        self._timeout_progreso = timeout_progreso
        self._lanzar = lanzar
        self._resolver = resolver
        self._identidad_de = identidad_de
        self._listar = listar
        self._dormir = dormir
        self._reloj = reloj
        self._pin = None            # ('by-id'|'by-path'|'nombre', valor) o None
        self._proc = None
        self._ultimo_progreso = 0.0

    # ------------------------------------------------------------------
    # Resolución del nodo con pin de identidad física (ADR-020)
    # ------------------------------------------------------------------

    def _nodo_para_lanzar(self, primera):
        """El /dev/videoN a transmitir, verificado contra el pin físico.

        Lanza RuntimeError (reintetable: el bucle hace backoff, salvo en el
        arranque, donde falla fuerte) o TransmisionFatal (salir ruidosamente).

        El arranque es estricto TAMBIÉN para el pin: si la identidad física no
        se puede fijar, no se transmite (hay un humano delante). Con eso el
        pin existe SIEMPRE en los relanzamientos — el hueco "pin nunca fijado
        -> relanzamientos sin verificación para siempre" (la clase del
        incidente de ADR-018 con un nodo literal robado por otra cámara)
        queda cerrado por construcción.
        """
        nodo = self._valor if self._clase == "literal" else self._resolver(self._valor)
        disp = self._identidad_de(nodo)

        if primera:
            if disp is None:
                raise RuntimeError(
                    f"no se pudo fijar la identidad física de "
                    f"{self._dispositivo_pedido!r} (el nodo {nodo} no aparece "
                    f"en la enumeración V4L2). ¿La cámara terminó de enumerar? "
                    f"Reintenta en unos segundos o revisa "
                    f"--listar-dispositivos; sin identidad física fijada los "
                    f"relanzamientos no podrían verificar la fuente."
                )
            self._pin = pin_de(disp, self._listar() or ())
            print(
                f"[{self._cama_id}] identidad física fijada: {self._pin[0]} "
                f"{self._pin[1]} (nodo {nodo})"
                + (". Nodo literal: cada relanzamiento verificará que siga "
                   "siendo la misma cámara." if self._clase == "literal" else ""),
                flush=True,
            )
            return nodo

        # Relanzamiento: el pin existe (el arranque falla fuerte sin él).
        if disp is None:
            # Fallback silencioso prohibido: sin enumeración no hay
            # verificación posible — esperar a que se estabilice (tormenta de
            # re-enumeración USB) es reintetable, transmitir a ciegas no.
            raise RuntimeError(
                f"no se pudo verificar la identidad física de {nodo} (no "
                f"aparece en la enumeración V4L2; ¿re-enumeración USB en "
                f"curso?); esperando"
            )
        if not coincide_pin(self._pin, disp):
            encontrado = pin_de(disp)
            if self._clase == "literal":
                # La clase exacta del incidente de ADR-018: el índice se
                # re-enumeró y ahora es OTRA cámara. Relanzar transmitiría la
                # cama equivocada: eso es fatal, no reintetable.
                raise TransmisionFatal(
                    f"El nodo literal {nodo} ahora corresponde a OTRO "
                    f"dispositivo físico (esperado {self._pin[0]} "
                    f"{self._pin[1]}, encontrado {encontrado[0]} "
                    f"{encontrado[1]}). NO se relanza: se estaría "
                    f"transmitiendo la cámara equivocada. Reconecta la cámara "
                    f"original o relanza con identidad estable "
                    f"(--listar-dispositivos)."
                )
            # Reintetable: la cámara original puede volver (se desenchufó y
            # otra parecida coincide con la aguja). Esperarla es lo seguro.
            raise RuntimeError(
                f"{self._valor!r} resolvió a OTRO dispositivo físico "
                f"(esperado {self._pin[0]} {self._pin[1]}, obtenido "
                f"{encontrado[0]} {encontrado[1]}); esperando a la cámara "
                f"original. Si el cambio de hardware es intencional (unidad "
                f"reemplazada o recableada), reinicia el runner para fijar "
                f"la nueva identidad"
            )
        return nodo

    # ------------------------------------------------------------------
    # Ciclo de vida del proceso
    # ------------------------------------------------------------------

    def _apagar(self, proc):
        """terminate -> gracia -> kill. Devuelve True si el proceso murió.

        False = ni SIGKILL lo mata: ffmpeg en sleep ININTERRUMPIBLE (estado D)
        dentro de un ioctl v4l2 con el driver colgado. Esperarlo sin tope
        colgaría al supervisor EN SILENCIO dentro de su propio camino de kill
        — por eso el wait post-kill está acotado y el fallo se reporta.
        """
        if proc is None or proc.poll() is not None:
            return True
        proc.terminate()
        try:
            proc.wait(timeout=GRACIA_TERMINATE_S)
            return True
        except subprocess.TimeoutExpired:
            pass
        proc.kill()
        try:
            proc.wait(timeout=ESPERA_KILL_S)
            return True
        except subprocess.TimeoutExpired:
            print(
                f"[{self._cama_id}] ffmpeg no muere ni con SIGKILL: proceso "
                f"en estado D (driver v4l2/xhci colgado). Revisa dmesg y "
                f"reconecta la cámara.",
                flush=True,
            )
            return False

    def _iniciar_lector_progreso(self, proc):
        """Hilo daemon que drena el -progress de ffmpeg y renueva la marca.

        Drenar es obligatorio (el pipe lleno bloquearía a ffmpeg). El hilo solo
        LEE; los Popen salen siempre del hilo principal (preexec_fn).
        Devuelve el hilo (o None si no hay stdout que drenar).
        """
        if getattr(proc, "stdout", None) is None:
            return None
        def leer():
            try:
                for _linea in proc.stdout:
                    self._ultimo_progreso = self._reloj()
            except Exception:
                pass  # el pipe muere con el proceso; el wait() ya lo reporta
        hilo = threading.Thread(
            target=leer, daemon=True, name=f"progreso-{self._cama_id}"
        )
        hilo.start()
        return hilo

    def _vigilar(self, proc):
        """Espera la salida del proceso vigilando el estancamiento.

        Devuelve (codigo, duracion, sano_s, estancado): `sano_s` es el tiempo
        con progreso REAL — en un estancamiento excluye la detección y la
        matanza (~14 s sin frames que, sumados al backoff-reset, harían girar
        en caliente a una cámara que se congela cada pocos segundos).
        KeyboardInterrupt emerge del wait() (PEP 475) y lo maneja correr().
        """
        t0 = self._reloj()
        self._ultimo_progreso = t0
        self._iniciar_lector_progreso(proc)
        estancado = False
        while True:
            try:
                codigo = proc.wait(timeout=_TICK_ESPERA_S)
                break
            except subprocess.TimeoutExpired:
                if self._reloj() - self._ultimo_progreso > self._timeout_progreso:
                    # ffmpeg vivo pero sin avanzar: cámara UVC atascada o TCP
                    # half-open. Un frame congelado que parece video en vivo es
                    # el pecado clínico; se derriba y se relanza.
                    estancado = True
                    if not self._apagar(proc):
                        # Ni SIGKILL: el dispositivo quedó secuestrado por un
                        # proceso inmatable — relanzar abriría OTRO ffmpeg
                        # contra un nodo ocupado. Salir ruidosamente.
                        raise TransmisionFatal(
                            "ffmpeg no muere ni con SIGKILL (driver v4l2 "
                            "colgado): el supervisor no puede garantizar la "
                            "fuente. Revisa dmesg, reconecta la cámara o "
                            "reinicia el equipo."
                        )
                    codigo = proc.poll()
                    break
        ahora = self._reloj()
        sano_s = (self._ultimo_progreso - t0) if estancado else (ahora - t0)
        return codigo, ahora - t0, sano_s, estancado

    def _espera(self, intento):
        return min(ESPERA_INICIAL_S * (2 ** min(intento, 6)), ESPERA_MAX_S)

    def _url(self):
        return f"rtsp://{self._servidor}:{self._puerto}/{self._cama_id}"

    def correr(self):
        """Bucle de supervisión. Solo vuelve por Ctrl+C/SIGTERM (limpio) o
        lanzando TransmisionFatal/RuntimeError-de-arranque (el CLI -> exit 1).
        """
        intento = 0
        primera = True
        try:
            while True:
                try:
                    nodo = self._nodo_para_lanzar(primera)
                except TransmisionFatal:
                    raise
                except RuntimeError as e:
                    if primera:
                        # Arranque estricto: hay un humano delante; un typo se
                        # corrige al momento (criterio del brief).
                        raise
                    espera = self._espera(intento)
                    intento += 1
                    print(f"[{self._cama_id}] {e}; reintento en {espera:.0f} s",
                          flush=True)
                    self._dormir(espera)
                    continue
                primera = False

                argv = comando_ffmpeg(
                    nodo, self._cama_id, self._servidor, self._puerto,
                    self._ancho, self._alto, self._fps, self._bitrate,
                    self._formato_entrada, progreso=True,
                )
                origen = f"{self._pin[0]} {self._pin[1]}" if self._pin else "sin pin"
                # Log de mapeo inequívoco en CADA (re)lanzamiento: la defensa
                # operativa contra "cámara equivocada por misconfig" (ADR-020).
                print(f"[{self._cama_id}] <- {origen} ({nodo}) -> {self._url()}",
                      flush=True)
                try:
                    proc = self._lanzar(argv, True)
                except FileNotFoundError:
                    raise TransmisionFatal(
                        "ffmpeg no está en el PATH: el entorno está roto y "
                        "reintentar no lo arregla. Instálalo (sudo apt "
                        "install ffmpeg) y relanza."
                    )
                self._proc = proc
                codigo, duracion, sano_s, estancado = self._vigilar(proc)
                self._proc = None

                if sano_s >= UMBRAL_SANO_S:
                    intento = 0  # corrió sano: el próximo fallo relanza en 1 s
                espera = self._espera(intento)
                intento += 1
                motivo = ("estancada (sin progreso de ffmpeg)" if estancado
                          else f"terminó (ffmpeg salió con código {codigo})")
                print(
                    f"[{self._cama_id}] transmisión {motivo} tras "
                    f"{duracion:.0f} s; reintento en {espera:.0f} s",
                    flush=True,
                )
                self._dormir(espera)
        except KeyboardInterrupt:
            print(f"\n[{self._cama_id}] Deteniendo...", flush=True)
        finally:
            try:
                self._apagar(self._proc)
            except KeyboardInterrupt:
                # Segundo Ctrl+C/SIGTERM durante el apagado: reintentar la
                # secuencia una vez para no dejar el ffmpeg vivo.
                self._apagar(self._proc)
            self._proc = None

    def una_vez(self):
        """Un solo lanzamiento sin supervisión (depuración de cámara/flags).

        Sin -progress (nadie drenaría el pipe) y passthrough del código de
        salida de ffmpeg. Acepta literales sin restricción: es el modo de
        depuración con el operador delante.
        """
        nodo = self._nodo_para_lanzar(primera=True)
        argv = comando_ffmpeg(
            nodo, self._cama_id, self._servidor, self._puerto,
            self._ancho, self._alto, self._fps, self._bitrate,
            self._formato_entrada, progreso=False,
        )
        print(f"[{self._cama_id}] (una vez) {nodo} -> {self._url()}", flush=True)
        try:
            proc = self._lanzar(argv, False)
        except FileNotFoundError:
            raise TransmisionFatal(
                "ffmpeg no está en el PATH: instálalo (sudo apt install "
                "ffmpeg) y relanza."
            )
        try:
            codigo = proc.wait()
        except KeyboardInterrupt:
            print(f"\n[{self._cama_id}] Deteniendo...", flush=True)
            self._apagar(proc)
            return 130
        # ffmpeg muerto por señal devuelve negativo en POSIX; sys.exit(-15)
        # saldría con 241 (módulo 256). Se normaliza a la convención shell
        # 128+N para que un script pueda interpretarlo.
        return 128 - codigo if codigo < 0 else codigo
