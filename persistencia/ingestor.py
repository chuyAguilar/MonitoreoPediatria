"""Núcleo de la ingesta: parseo puro del contrato + servicio MQTT → SQLite.

Diseño (ADR-021):

- El hilo de red de paho SOLO parsea y encola; el hilo principal (dueño de la
  conexión SQLite) drena la cola y escribe en lote — un commit por lote, no
  por mensaje (eMMC).
- TODO el cuerpo de `al_recibir` va bajo `except Exception`: en paho v2
  (`suppress_exceptions=False`) una excepción del callback MATA el hilo de red
  sin reconexión, con el proceso "active" para systemd — el fallo silencioso
  exacto que este proyecto prohíbe.
- El lote se retira de la cola SOLO DESPUÉS del commit: una señal entre el
  drenado y el commit no puede perder filas (siguen en la cola).
- Lote envenenado: si `executemany` falla, rollback y reintento fila a fila
  para aislar y descartar la fila tóxica con log — nunca reintentar el lote
  entero para siempre.
- Parseo SIN re-validación clínica (ni rangos ni coherencia: el OCR ya mandó
  aguas arriba) pero con disciplina DURA de tipos por columna: `bool` no es
  int (`{"valor": true}` sería una fc=1 de aspecto plausible), int solo dentro
  de 64 bits (10**20 haría fallar el bind eternamente), float solo finito
  (json.loads acepta NaN/Infinity), ts solo str (un epoch numérico en columna
  TEXT ordena antes que todo texto y los BETWEEN lo excluyen en silencio).
  Campo AUSENTE → su columna NULL sin marca (el simulador publica contrato 1.0
  sin `confianza`: es legítimo). Campo PRESENTE con forma rota → su columna
  NULL + `malformado=1`; si el valor de un signo está roto, su confianza
  también va a NULL (jamás una confianza huérfana, que el contrato hace
  imposible).
- Sesión persistente MQTT (`clean_session=False` + client_id fijo): el broker
  encola los QoS 1 mientras la ingesta está caída — un deploy no perfora el
  histórico. Exige UNA sola instancia (dos con el mismo client_id se expulsan
  mutuamente en bucle). La re-suscripción vive en on_connect (paho no re-manda
  SUBSCRIBE solo) y revisa el reason_code: un CONNACK rechazado repetido
  (auth futura de Mosquitto) termina el servicio con error visible en vez de
  reintentar "active" para siempre sin ingerir.
"""

import json
import math
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import NamedTuple, Optional

# Topics del contrato (réplica deliberada de ocr/publicador.py, que es de
# publicador; ver docs/ito2/CONTRATO_DATOS.md)
SUSCRIPCION_VITALES = "monitoreo/vitales/+"
SUSCRIPCION_ESTADO = "monitoreo/estado/+"
_PREFIJO_VITALES = "monitoreo/vitales/"
_PREFIJO_ESTADO = "monitoreo/estado/"

LOTE_DEFECTO = 100            # N: vaciado inmediato al acumularse
INTERVALO_DEFECTO_S = 5.0     # T: vaciado periódico
MAX_PENDIENTES = 10_000       # tope de cola (~20 min a 10 msg/s): nunca OOM
TOPE_PAYLOAD_BYTES = 64 * 1024  # los mensajes del contrato miden < 1 KB
RESUMEN_CADA_S = 60.0
MAX_CONNACK_RECHAZADOS = 5

_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1

CLIENT_ID = "ingesta-vitales"


def _ahora_iso() -> str:
    """ISO UTC del servidor (réplica del patrón de ocr/tiempo.py)."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Guardas de forma por columna: (valor_para_la_columna, forma_ok)
# forma_ok=False => el campo estaba PRESENTE con forma rota (marca malformado)
# ---------------------------------------------------------------------------


def _entero(v):
    if type(v) is int and _INT64_MIN <= v <= _INT64_MAX:
        return v, True
    return None, v is None


def _real(v):
    if type(v) is bool:
        return None, False
    if type(v) is int and _INT64_MIN <= v <= _INT64_MAX:
        return float(v), True
    if type(v) is float and math.isfinite(v):
        return v, True
    return None, v is None


def _texto(v):
    if type(v) is str:
        return v, True
    return None, v is None


def _signo(signos, clave, guarda_valor):
    """(valor, confianza, forma_ok) de un signo simple del contrato.

    Signo ausente o null → NULLs sin marca. `confianza` ausente → NULL sin
    marca (contrato 1.0 del simulador). Valor roto → confianza también NULL.
    """
    if type(signos) is not dict:
        return None, None, False
    s = signos.get(clave)
    if s is None:
        return None, None, True
    if type(s) is not dict:
        return None, None, False
    if "valor" not in s:
        # Un signo-objeto SIN valor es forma rota (el contrato siempre lo
        # trae); persistir su confianza sola sería el par huérfano que el
        # contrato hace imposible.
        return None, None, False
    valor, ok_valor = guarda_valor(s.get("valor"))
    if "confianza" in s:
        conf, ok_conf = _real(s.get("confianza"))
    else:
        conf, ok_conf = None, True
    if not ok_valor:
        conf = None
    return valor, conf, ok_valor and ok_conf


def _pni(signos):
    """(sis, dia, media, conf, pni_ts, forma_ok). `pni: null` es legítimo."""
    if type(signos) is not dict:
        return None, None, None, None, None, False
    p = signos.get("pni")
    if p is None:
        return None, None, None, None, None, True
    if type(p) is not dict:
        return None, None, None, None, None, False
    # Un componente AUSENTE en un pni-objeto es forma rota: el contrato emite
    # el trío completo o pni:null ("ni parcial ni incoherente") — una presión
    # parcial sin marca pasaría el filtro de lectura limpia siendo justo el
    # dato engañoso que el emisor prohíbe.
    sis, ok_s = _entero(p.get("sis")) if "sis" in p else (None, False)
    dia, ok_d = _entero(p.get("dia")) if "dia" in p else (None, False)
    media, ok_m = _entero(p.get("media")) if "media" in p else (None, False)
    if "confianza" in p:
        conf, ok_c = _real(p.get("confianza"))
    else:
        conf, ok_c = None, True
    if "ts" in p:
        pni_ts, ok_t = _texto(p.get("ts"))
    else:
        pni_ts, ok_t = None, True
    if not (ok_s and ok_d and ok_m):
        conf = None
    return sis, dia, media, conf, pni_ts, all((ok_s, ok_d, ok_m, ok_c, ok_t))


class FilaVitales(NamedTuple):
    contrato: Optional[str]
    cama_id: Optional[str]
    device_id: Optional[str]
    origen: Optional[str]
    ts: Optional[str]
    recibido_en: str
    topic: str
    retenido: int
    malformado: int
    fc: Optional[int]
    fc_conf: Optional[float]
    spo2: Optional[int]
    spo2_conf: Optional[float]
    fp: Optional[int]
    fp_conf: Optional[float]
    fr: Optional[int]
    fr_conf: Optional[float]
    temp: Optional[float]
    temp_conf: Optional[float]
    pni_sis: Optional[int]
    pni_dia: Optional[int]
    pni_media: Optional[int]
    pni_conf: Optional[float]
    pni_ts: Optional[str]
    raw: bytes


class FilaEstado(NamedTuple):
    cama_id: Optional[str]
    device_id: Optional[str]
    estado: Optional[str]
    ts: Optional[str]
    recibido_en: str
    topic: str
    retenido: int
    malformado: int
    raw: bytes


def _objeto_json(payload):
    """El dict del payload, o None (no-JSON / no-objeto: se salta con log)."""
    try:
        m = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    return m if type(m) is dict else None


def fila_de_vitales(topic, payload, retenido, recibido_en):
    """FilaVitales o None (solo lo no-JSON/no-objeto se salta; lo roto se
    persiste con NULLs + malformado=1 — criterio de aceptación redefinido y
    aprobado en la iteración 10)."""
    m = _objeto_json(payload)
    if m is None:
        return None
    contrato, ok1 = _texto(m.get("contrato"))
    cama_id, ok2 = _texto(m.get("cama_id"))
    device_id, ok3 = _texto(m.get("device_id"))
    origen, ok4 = _texto(m.get("origen"))
    ts, ok5 = _texto(m.get("ts"))
    signos = m.get("signos")
    fc, fc_conf, ok_fc = _signo(signos, "fc", _entero)
    spo2, spo2_conf, ok_spo2 = _signo(signos, "spo2", _entero)
    fp, fp_conf, ok_fp = _signo(signos, "fp", _entero)
    fr, fr_conf, ok_fr = _signo(signos, "fr", _entero)
    temp, temp_conf, ok_temp = _signo(signos, "temp", _real)
    pni_sis, pni_dia, pni_media, pni_conf, pni_ts, ok_pni = _pni(signos)
    forma_ok = all((ok1, ok2, ok3, ok4, ok5, ok_fc, ok_spo2, ok_fp, ok_fr,
                    ok_temp, ok_pni))
    return FilaVitales(
        contrato=contrato, cama_id=cama_id, device_id=device_id, origen=origen,
        ts=ts, recibido_en=recibido_en, topic=topic,
        retenido=1 if retenido else 0, malformado=0 if forma_ok else 1,
        fc=fc, fc_conf=fc_conf, spo2=spo2, spo2_conf=spo2_conf,
        fp=fp, fp_conf=fp_conf, fr=fr, fr_conf=fr_conf,
        temp=temp, temp_conf=temp_conf,
        pni_sis=pni_sis, pni_dia=pni_dia, pni_media=pni_media,
        pni_conf=pni_conf, pni_ts=pni_ts,
        raw=bytes(payload),
    )


def fila_de_estado(topic, payload, retenido, recibido_en):
    m = _objeto_json(payload)
    if m is None:
        return None
    cama_id, ok1 = _texto(m.get("cama_id"))
    device_id, ok2 = _texto(m.get("device_id"))
    estado, ok3 = _texto(m.get("estado"))
    ts, ok4 = _texto(m.get("ts"))
    return FilaEstado(
        cama_id=cama_id, device_id=device_id, estado=estado, ts=ts,
        recibido_en=recibido_en, topic=topic,
        retenido=1 if retenido else 0,
        malformado=0 if all((ok1, ok2, ok3, ok4)) else 1,
        raw=bytes(payload),
    )


def _cama_de_topic(topic):
    return topic.rsplit("/", 1)[-1] if "/" in topic else None


def _resumen_payload(payload):
    """Para logs: tamaño + primeros 80 caracteres, JAMÁS el payload completo
    (journald no debe volverse una segunda BD de datos de menores)."""
    return f"{len(payload)} bytes, {payload[:80]!r}"


class ServicioIngesta:
    """Cola compartida + escritura en lote. El hilo principal llama correr().

    Costuras inyectables (los tests no usan broker ni hilos de paho; el hilo
    de red REAL de paho solo lo cubre la prueba de aceptación en el servidor):
    `reloj` (monotónico), `ahora` (ISO para recibido_en/eventos).
    """

    def __init__(self, almacen, lote=LOTE_DEFECTO, intervalo_s=INTERVALO_DEFECTO_S,
                 reloj=time.monotonic, ahora=_ahora_iso):
        self._almacen = almacen
        self._lote = lote
        self._intervalo = intervalo_s
        self._reloj = reloj
        self._ahora = ahora
        self._pendientes = deque()   # (es_vitales: bool, fila: NamedTuple)
        self._lock = threading.Lock()
        self._hay_trabajo = threading.Event()
        self._descartados = 0
        self._descartados_desde = None
        self._escritas_total = 0
        self._escritas_minuto = 0
        self._connack_rechazados = 0
        self._conexion_rechazada = None  # str = motivo fatal
        self._reintentar_desde = None    # reloj: backoff con SQLite caída

    # ----------------------------------------------------------------- MQTT

    def al_conectar(self, cliente, _userdata, flags, reason_code, _properties=None):
        """Callback on_connect de paho v2: re-suscribe en CADA (re)conexión.

        La visibilidad de los episodios de conectividad la dan ESTOS logs
        (junto a al_desconectar): los mensajes de reconexión internos de paho
        son nivel DEBUG y no llegan a journald.
        """
        try:
            if getattr(reason_code, "is_failure", False):
                self._connack_rechazados += 1
                print(f"[ingesta] conexión rechazada por el broker "
                      f"({reason_code}), intento {self._connack_rechazados}/"
                      f"{MAX_CONNACK_RECHAZADOS}", flush=True)
                if self._connack_rechazados >= MAX_CONNACK_RECHAZADOS:
                    # Sin esto el servicio quedaría "active" reintentando para
                    # siempre sin ingerir (fallo silencioso prohibido).
                    self._conexion_rechazada = (
                        f"el broker rechaza la conexión ({reason_code}): "
                        f"revisa credenciales/config de Mosquitto"
                    )
                    self._hay_trabajo.set()  # despierta al hilo principal
                return
            self._connack_rechazados = 0
            sesion = ("sesión retomada — el broker encoló durante la ausencia"
                      if getattr(flags, "session_present", False)
                      else "sesión nueva")
            print(f"[ingesta] conectado al broker ({sesion}); suscribiendo",
                  flush=True)
            resultado, _mid = cliente.subscribe(
                [(SUSCRIPCION_VITALES, 1), (SUSCRIPCION_ESTADO, 1)])
            if resultado != 0:
                # Socket caído entre CONNACK y SUBSCRIBE: paho reconectará y
                # volverá a entrar aquí — visible, no silencioso.
                print(f"[ingesta] subscribe devolvió {resultado}; se "
                      f"reintentará en la reconexión", flush=True)
        except Exception as e:
            print(f"[ingesta] error en on_connect: {e}", flush=True)

    def al_suscribir(self, _cliente, _userdata, _mid, reason_codes, _properties=None):
        """Callback on_subscribe: vigila el SUBACK — una ACL futura puede
        aceptar la conexión y RECHAZAR la suscripción; sin esta guardia el
        servicio quedaría 'conectado' sin ingerir jamás, en silencio."""
        try:
            fallos = [str(rc) for rc in reason_codes
                      if getattr(rc, "is_failure", False)]
            if fallos:
                self._conexion_rechazada = (
                    f"el broker rechazó la suscripción ({', '.join(fallos)}): "
                    f"¿ACL de Mosquitto? Sin suscripción no hay ingesta."
                )
                self._hay_trabajo.set()
            else:
                print("[ingesta] suscripción confirmada por el broker",
                      flush=True)
        except Exception as e:
            print(f"[ingesta] error en on_subscribe: {e}", flush=True)

    def al_desconectar(self, _cliente, _userdata, _flags, reason_code,
                       _properties=None):
        """Callback on_disconnect: deja rastro del hueco de conectividad."""
        try:
            print(f"[ingesta] desconectado del broker ({reason_code}); paho "
                  f"reintenta solo (la sesión persistente encola)", flush=True)
        except Exception:
            pass

    def al_recibir(self, _cliente, _userdata, mensaje):
        """Callback on_message de paho: TODO bajo except (ver docstring)."""
        try:
            self._procesar(mensaje.topic, mensaje.payload, bool(mensaje.retain))
        except Exception as e:
            try:
                print(f"[ingesta] error procesando {mensaje.topic}: {e}",
                      flush=True)
            except Exception:
                pass

    def _procesar(self, topic, payload, retenido):
        if len(payload) > TOPE_PAYLOAD_BYTES:
            print(f"[ingesta] descartado {topic}: {len(payload)} bytes supera "
                  f"el tope de {TOPE_PAYLOAD_BYTES} (los mensajes del contrato "
                  f"miden <1 KB; ¿publicador ajeno?)", flush=True)
            return
        recibido_en = self._ahora()
        if topic.startswith(_PREFIJO_VITALES):
            es_vitales, fila = True, fila_de_vitales(topic, payload, retenido, recibido_en)
        elif topic.startswith(_PREFIJO_ESTADO):
            es_vitales, fila = False, fila_de_estado(topic, payload, retenido, recibido_en)
        else:
            print(f"[ingesta] descartado: topic inesperado {topic!r}", flush=True)
            return
        if fila is None:
            print(f"[ingesta] descartado {topic}: no es un objeto JSON "
                  f"({_resumen_payload(payload)})", flush=True)
            return
        if es_vitales and fila.contrato is not None and not fila.contrato.startswith("1."):
            # Un contrato 2.x puede renombrar campos o cambiar unidades: se
            # persiste igual (raw íntegro + columna contrato) pero JAMÁS en
            # silencio.
            print(f"[ingesta] AVISO {topic}: contrato {fila.contrato!r} "
                  f"desconocido (este código entiende 1.x); revisa el mapeo "
                  f"de columnas", flush=True)
        cama_topic = _cama_de_topic(topic)
        if fila.cama_id is not None and cama_topic is not None and fila.cama_id != cama_topic:
            # cama_id manda el del payload (es lo que el contrato firma); el
            # topic queda en su columna como rastro de auditoría.
            print(f"[ingesta] AVISO {topic}: el payload afirma cama_id="
                  f"{fila.cama_id!r} distinto del topic", flush=True)
        self._encolar(es_vitales, fila)

    def _encolar(self, es_vitales, fila):
        with self._lock:
            if len(self._pendientes) >= MAX_PENDIENTES:
                self._pendientes.popleft()
                self._descartados += 1
                if self._descartados_desde is None:
                    self._descartados_desde = self._ahora()
            self._pendientes.append((es_vitales, fila))
            n = len(self._pendientes)
        if n >= self._lote:
            self._hay_trabajo.set()

    # ------------------------------------------------------------ escritura

    def correr(self):
        """Bucle del hilo principal (dueño de SQLite). Ctrl+C/SIGTERM salen
        limpio; el vaciado FINAL lo orquesta el CLI (tras parar el cliente).
        Lanza RuntimeError si el broker rechaza la conexión repetidamente."""
        self._almacen.registrar_evento(
            self._ahora(), "arranque",
            f"lote={self._lote} intervalo={self._intervalo}s "
            f"tope={MAX_PENDIENTES}",
        )
        ultimo_resumen = self._reloj()
        try:
            while True:
                self._hay_trabajo.wait(timeout=self._intervalo)
                self._hay_trabajo.clear()
                if self._conexion_rechazada:
                    raise RuntimeError(self._conexion_rechazada)
                self._vaciar()
                ahora = self._reloj()
                if ahora - ultimo_resumen >= RESUMEN_CADA_S:
                    with self._lock:
                        en_cola = len(self._pendientes)
                    print(f"[ingesta] {self._escritas_minuto} filas escritas "
                          f"en el último minuto ({self._escritas_total} en "
                          f"total, {en_cola} en cola)", flush=True)
                    self._escritas_minuto = 0
                    ultimo_resumen = ahora
        except KeyboardInterrupt:
            print("\n[ingesta] Deteniendo...", flush=True)

    def vaciar_final(self):
        """Último vaciado del cierre, protegido de una segunda señal."""
        try:
            self._vaciar()
        except KeyboardInterrupt:
            self._vaciar()

    def _vaciar(self):
        """Drena y escribe. El lote se retira de la cola SOLO tras el commit."""
        if self._reintentar_desde is not None:
            # SQLite caída: backoff — sin esto, con la cola por encima de N,
            # CADA mensaje entrante re-armaría el Event y el reintento sería
            # por mensaje (trabajo máximo justo cuando el disco está peor).
            if self._reloj() < self._reintentar_desde:
                return
            self._reintentar_desde = None
        with self._lock:
            lote = list(self._pendientes)  # copia SIN retirar
        if lote:
            vitales = [f for es_v, f in lote if es_v]
            estados = [f for es_v, f in lote if not es_v]
            try:
                self._almacen.insertar_lote(vitales, estados)
                escritas = len(lote)
            except KeyboardInterrupt:
                # La cola sigue intacta: nada se pierde. Deshacer ANTES de
                # re-lanzar: la transacción abierta ya contiene las filas y el
                # reintento del cierre las DUPLICARÍA en el histórico.
                try:
                    self._almacen.deshacer()
                except Exception:
                    pass
                raise
            except Exception as e:
                escritas = self._aislar_veneno(lote, e)
                if escritas is None:
                    # Conservar la cola y reintentar tras el intervalo
                    self._reintentar_desde = self._reloj() + self._intervalo
                    return
            # El retiro también va protegido: una señal entre el commit y el
            # fin del retiro dejaría el lote commiteado en la cola, y el
            # vaciado final lo re-insertaría entero (_retirar es re-ejecutable
            # con seguridad: salta por identidad lo ya retirado; `cuenta`
            # sobrevive al reintento para ajustar los descartes UNA sola vez).
            cuenta = {"retiradas": 0}
            try:
                self._retirar(lote, cuenta)
            except KeyboardInterrupt:
                self._retirar(lote, cuenta)
                self._ajustar_descartes(len(lote) - cuenta["retiradas"])
                raise
            self._ajustar_descartes(len(lote) - cuenta["retiradas"])
            self._escritas_total += escritas
            self._escritas_minuto += escritas
        self._registrar_descartes_si_hubo()

    def _aislar_veneno(self, lote, error_lote):
        """Reintento fila a fila para aislar la fila no-insertable.

        Devuelve cuántas se escribieron, o None si SQLite está caída (disco
        lleno, BD bloqueada): en ese caso la cola se conserva entera y se
        reintenta al siguiente tick — nunca girar para siempre sobre un lote
        envenenado, nunca descartar por un fallo transitorio del disco.
        """
        print(f"[ingesta] el lote falló ({error_lote}); aislando fila a fila",
              flush=True)
        try:
            self._almacen.deshacer()
            escritas = 0
            for es_vitales, fila in lote:
                try:
                    self._almacen.insertar_fila(es_vitales, fila)
                    escritas += 1
                except (ValueError, TypeError, OverflowError,
                        sqlite3.InterfaceError, sqlite3.ProgrammingError) as e:
                    # Fila no-bindeable (veneno; sqlite3 lanza Interface/
                    # ProgrammingError al fallar el bind): descartarla con
                    # log; el resto del lote se persiste. OperationalError
                    # (disco lleno, BD bloqueada) NO es veneno: cae al except
                    # exterior y se conserva la cola.
                    print(f"[ingesta] fila descartada (no insertable, "
                          f"topic={fila.topic}): {e}", flush=True)
            self._almacen.confirmar()
            return escritas
        except KeyboardInterrupt:
            # Mismo motivo que en _vaciar: sin rollback, el reintento del
            # cierre duplicaría lo ya insertado en la transacción abierta.
            try:
                self._almacen.deshacer()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                self._almacen.deshacer()
            except Exception:
                pass
            print(f"[ingesta] SQLite no disponible; se reintenta el lote "
                  f"entero al siguiente tick: {e}", flush=True)
            return None

    def _retirar(self, lote, cuenta):
        """Retira de la cola exactamente los items procesados, por identidad
        (el tope pudo descartar por la izquierda mientras escribíamos).
        `cuenta["retiradas"]` acumula a través de un reintento tras señal."""
        with self._lock:
            i = 0
            while self._pendientes and i < len(lote):
                if self._pendientes[0] is lote[i]:
                    self._pendientes.popleft()
                    cuenta["retiradas"] += 1
                i += 1

    def _ajustar_descartes(self, ya_persistidas):
        """Items del lote que el tope descartó DURANTE la escritura quedaron
        persistidos igualmente: se restan del contador — sin esto, el evento
        de auditoría afirmaría un hueco que no existe (falso positivo)."""
        if ya_persistidas <= 0:
            return
        with self._lock:
            self._descartados = max(0, self._descartados - ya_persistidas)
            if self._descartados == 0:
                self._descartados_desde = None

    def _registrar_descartes_si_hubo(self):
        with self._lock:
            n, desde = self._descartados, self._descartados_desde
            self._descartados, self._descartados_desde = 0, None
        if n:
            # El hueco queda explicado EN el histórico (no solo en journald,
            # que rota y que durante un disco lleno también sufre).
            try:
                self._almacen.registrar_evento(
                    self._ahora(), "descarte",
                    f"{n} mensajes descartados por tope de cola desde {desde}",
                )
            except Exception as e:
                with self._lock:
                    self._descartados += n
                    self._descartados_desde = self._descartados_desde or desde
                print(f"[ingesta] no se pudo registrar el descarte ({e}); "
                      f"se reintentará", flush=True)


def crear_cliente_suscriptor(broker, puerto, servicio, client_id=CLIENT_ID):
    """Cliente paho v2 suscriptor con sesión persistente (import perezoso).

    - Callbacks asignados ANTES de conectar (ningún mensaje se pierde entre
      connect y el wiring).
    - `clean_session=False` + client_id fijo: el broker encola los QoS 1
      mientras la ingesta está caída. UNA sola instancia por client_id.
    - La visibilidad de reconexiones la dan los callbacks al_conectar /
      al_desconectar / al_suscribir (los logs internos de paho son DEBUG y no
      llegan a journald; `enable_logger()` solo hace visibles sus WARN/ERR).
    - Arranque estricto: si el TCP no conecta, lanza (el CLI → exit 1; el boot
      lo sana systemd con After=mosquitto + Restart=on-failure).
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError as e:
        raise RuntimeError(
            "Falta paho-mqtt para la ingesta. Instala: pip install paho-mqtt"
        ) from e
    cliente = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=False,
    )
    cliente.enable_logger()
    cliente.on_connect = servicio.al_conectar
    cliente.on_subscribe = servicio.al_suscribir
    cliente.on_disconnect = servicio.al_desconectar
    cliente.on_message = servicio.al_recibir
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    cliente.connect(broker, puerto, keepalive=60)
    cliente.loop_start()
    return cliente


def apagar_cliente(cliente):
    """loop_stop + disconnect si el cliente los expone (el falso no).

    Un disconnect limpio NO borra la sesión persistente: el broker sigue
    encolando los QoS 1 hasta que la ingesta vuelva.
    """
    for metodo in ("loop_stop", "disconnect"):
        fn = getattr(cliente, metodo, None)
        if callable(fn):
            fn()
