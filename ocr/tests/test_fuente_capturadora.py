"""FuenteCapturadora probada sin hardware: cv2.VideoCapture se sustituye por un falso.

Lo que se fija aquí es el comportamiento medido en el banco físico (Jetson +
capturadora HDMI→USB): MJPG 1920x1080, ~15 frames negros de arranque, y la
política de seguridad ante fallo de lectura — reintentos acotados y luego
LANZAR, nunca servir un frame viejo como si fuera actual.
"""

import cv2
import numpy as np
import pytest

from ocr.fuente import FuenteCapturadora

ANCHO, ALTO = 1920, 1080
FOURCC_MJPG = cv2.VideoWriter_fourcc(*"MJPG")


def _frame(marca, ancho=ANCHO, alto=ALTO):
    """Frame BGR distinguible: la marca va en el píxel (0,0,canal azul)."""
    frame = np.zeros((alto, ancho, 3), dtype=np.uint8)
    frame[0, 0, 0] = marca % 256
    return frame


class CapturaFalsa:
    """Imita cv2.VideoCapture: registra set()/grab()/read() y sirve lecturas programadas."""

    def __init__(self, dispositivo, preferencia=None):
        self.dispositivo = dispositivo
        self.preferencia = preferencia
        self.abierta = True
        self.liberada = False
        self.sets = []          # [(prop, valor)] en orden
        self.llamadas = []      # secuencia de "grab"/"read" (fija el drenado)
        self.n_lecturas = 0
        self.plan = None        # función n_lectura -> (ok, frame); None = frames marcados

    def isOpened(self):
        return self.abierta

    def set(self, prop, valor):
        self.sets.append((prop, valor))
        return True

    def _consumir(self):
        self.n_lecturas += 1
        if self.plan is not None:
            return self.plan(self.n_lecturas)
        return True, _frame(self.n_lecturas)

    def grab(self):
        """Como el real: consume un frame de la cola y solo informa éxito."""
        self.llamadas.append("grab")
        ok, _ = self._consumir()
        return ok

    def read(self):
        self.llamadas.append("read")
        return self._consumir()

    def release(self):
        self.liberada = True


@pytest.fixture()
def captura(monkeypatch):
    """Parcha cv2.VideoCapture dentro de ocr.fuente y expone la instancia falsa."""
    creadas = []

    def fabrica(dispositivo, preferencia=None):
        instancia = CapturaFalsa(dispositivo, preferencia)
        if creadas:
            # los tests de este módulo abren un solo dispositivo
            raise AssertionError("se abrió más de un VideoCapture")
        creadas.append(instancia)
        return instancia

    monkeypatch.setattr("ocr.fuente.cv2.VideoCapture", fabrica)
    return creadas


def test_fija_buffer_1_y_mjpg_antes_que_la_resolucion(captura):
    FuenteCapturadora("/dev/video0")
    props = captura[0].sets
    # Cola de 1: sin esto, el backend V4L2 sirve el frame MÁS VIEJO de una
    # cola de 4 — a 1 Hz serían frames de ~4 s publicados con ts fresco.
    assert props[0] == (cv2.CAP_PROP_BUFFERSIZE, 1)
    assert (cv2.CAP_PROP_FRAME_WIDTH, ANCHO) in props
    assert (cv2.CAP_PROP_FRAME_HEIGHT, ALTO) in props
    assert props.index((cv2.CAP_PROP_FOURCC, FOURCC_MJPG)) < props.index(
        (cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
    )


def test_cada_lectura_drena_con_grab_antes_del_read(captura):
    """El frame servido debe capturarse DESPUÉS de la llamada: grab() drena
    el posible frame encolado del tick anterior y read() sirve el fresco."""
    fuente = FuenteCapturadora("/dev/video0")
    captura[0].llamadas.clear()
    fuente.frame()
    assert captura[0].llamadas == ["grab", "read"]


def test_usa_v4l2_y_acepta_indice_numerico(captura):
    FuenteCapturadora("0")
    assert captura[0].dispositivo == 0            # "0" -> índice entero
    assert captura[0].preferencia == cv2.CAP_V4L2


# --------------------------------------------------------------------------
# Identidad estable (ADR-018): serial/nombre se resuelve al nodo de captura;
# rutas e índices explícitos NUNCA pasan por el resolutor (el usuario manda).
# --------------------------------------------------------------------------


def test_identidad_estable_se_resuelve_antes_de_abrir(captura, monkeypatch):
    from ocr import dispositivos

    resueltos = []

    def resolver_falso(identificador):
        resueltos.append(identificador)
        return "/dev/video2"

    monkeypatch.setattr(dispositivos, "resolver", resolver_falso)
    fuente = FuenteCapturadora("35562055")
    assert resueltos == ["35562055"]
    assert captura[0].dispositivo == "/dev/video2"   # abre el nodo RESUELTO
    # la trazabilidad para el operador: identidad -> nodo
    assert "35562055" in repr(fuente) and "/dev/video2" in repr(fuente)


@pytest.mark.parametrize("literal", ["/dev/video0", "/dev/v4l/by-id/usb-x-video-index0", "2", "999"])
def test_ruta_o_indice_literal_no_pasa_por_el_resolutor(captura, monkeypatch, literal):
    from ocr import dispositivos

    def resolver_prohibido(identificador):
        raise AssertionError("un literal no debe resolverse")

    monkeypatch.setattr(dispositivos, "resolver", resolver_prohibido)
    FuenteCapturadora(literal)                       # no lanza: no resolvió


def test_serial_numerico_largo_es_identidad_no_indice(captura, monkeypatch):
    """"35562055" (el serial real) debe resolverse, no abrir la cámara nº 35562055.

    La frontera es determinista: dígitos de <=3 caracteres = índice V4L2
    ("0".."999", ningún /dev/videoN real pasa de ahí); más largos = identidad.
    """
    from ocr import dispositivos

    monkeypatch.setattr(dispositivos, "resolver", lambda ident: "/dev/video2")
    FuenteCapturadora("35562055")
    assert captura[0].dispositivo == "/dev/video2"   # resolvió, no índice gigante


def test_frontera_1000_es_identidad(captura, monkeypatch):
    """El OTRO lado de la frontera: "1000" (4 dígitos) va al resolutor.

    Fija la frontera por ambos lados: una regresión a `len <= 4` dejaría este
    test en rojo (abriría el índice 1000 sin resolver)."""
    from ocr import dispositivos

    resueltos = []

    def resolver_espia(identificador):
        resueltos.append(identificador)
        return "/dev/video2"

    monkeypatch.setattr(dispositivos, "resolver", resolver_espia)
    FuenteCapturadora("1000")
    assert resueltos == ["1000"]                     # identidad, no índice


def test_whitespace_no_convierte_un_indice_en_identidad(captura, monkeypatch):
    """" 0" (un espacio de un unit file) es el índice 0, no una identidad.

    Sin el strip previo a la clasificación, " 0" caía a la rama de identidad y
    la aguja "0" coincidiría por subcadena con el by-path de casi cualquier
    dispositivo — otra vía a abrir la fuente equivocada en silencio."""
    from ocr import dispositivos

    def resolver_prohibido(identificador):
        raise AssertionError("un índice con espacios no debe resolverse")

    monkeypatch.setattr(dispositivos, "resolver", resolver_prohibido)
    FuenteCapturadora(" 0")
    assert captura[0].dispositivo == 0


def test_whitespace_alrededor_de_ruta_se_normaliza(captura, monkeypatch):
    from ocr import dispositivos

    def resolver_prohibido(identificador):
        raise AssertionError("una ruta con espacios no debe resolverse")

    monkeypatch.setattr(dispositivos, "resolver", resolver_prohibido)
    FuenteCapturadora(" /dev/video2 ")
    assert captura[0].dispositivo == "/dev/video2"


def test_whitespace_alrededor_de_identidad_se_normaliza(captura, monkeypatch):
    from ocr import dispositivos

    resueltos = []
    monkeypatch.setattr(dispositivos, "resolver",
                        lambda ident: resueltos.append(ident) or "/dev/video2")
    FuenteCapturadora(" 35562055 ")
    assert resueltos == ["35562055"]                 # llega ya sin espacios


def test_identidad_ausente_no_abre_ninguna_fuente(captura, monkeypatch):
    """Regresión del incidente: sin la identidad pedida, NADA se abre."""
    from ocr import dispositivos

    def resolver_fallido(identificador):
        raise RuntimeError(f"No hay ningún dispositivo que coincida con {identificador!r}")

    monkeypatch.setattr(dispositivos, "resolver", resolver_fallido)
    with pytest.raises(RuntimeError, match="Elgato"):
        FuenteCapturadora("Elgato")
    assert captura == []                             # ningún VideoCapture creado


def test_cli_identidad_ausente_sale_limpio(monkeypatch, capsys):
    from ocr import dispositivos, publicar

    def resolver_fallido(identificador):
        raise RuntimeError(f"No hay ningún dispositivo que coincida con {identificador!r}. "
                           f"Usa --listar-dispositivos.")

    monkeypatch.setattr(dispositivos, "resolver", resolver_fallido)
    codigo = publicar.main(["--fuente", "capturadora", "--dispositivo", "Elgato",
                            "--motor", "plantilla", "--solo-consola"])
    assert codigo == 1
    salida = capsys.readouterr().out
    assert "Elgato" in salida and "listar-dispositivos" in salida


def test_cli_listar_dispositivos(monkeypatch, capsys):
    from ocr import publicar
    from ocr.dispositivos import DispositivoCaptura

    detectado = DispositivoCaptura(
        nombre="USB3 Video: USB3 Video",
        by_id="usb-UltraSemi_USB3_Video_35562055",
        by_path="platform-3610000.usb-usb-0:1.3:1.0",
        serial="35562055",
        nodos=(("/dev/video2", 0x1), ("/dev/video3", 0x800000)),
        nodos_captura=("/dev/video2",),
        nodo_captura="/dev/video2",
    )
    import ocr.dispositivos as dispositivos
    monkeypatch.setattr(dispositivos, "listar_dispositivos", lambda: [detectado])
    assert publicar.main(["--listar-dispositivos"]) == 0
    salida = capsys.readouterr().out
    assert "35562055" in salida and "/dev/video2[captura]" in salida


def test_cli_listar_corta_antes_de_construir_fuente_o_motor(monkeypatch, capsys):
    """--listar-dispositivos es el flag de diagnóstico: sale ANTES de construir
    fuente/perfil/motor — no exige RapidOCR, no resuelve ni abre dispositivo.

    Se invoca con la forma de campo del incidente (--fuente capturadora
    --dispositivo 35562055 --listar-dispositivos): el listado manda igual."""
    import ocr.dispositivos as dispositivos
    from ocr import publicar
    from ocr.dispositivos import DispositivoCaptura

    def prohibido(*a, **k):
        raise AssertionError("--listar-dispositivos no debe construir fuente/perfil/motor")

    monkeypatch.setattr(publicar, "FuenteCapturadora", prohibido)
    monkeypatch.setattr(publicar, "FuenteImagenFija", prohibido)
    monkeypatch.setattr(publicar, "cargar_perfil", prohibido)
    monkeypatch.setattr(publicar, "_construir_motor", prohibido)
    monkeypatch.setattr(publicar, "correr", prohibido)

    detectado = DispositivoCaptura(
        nombre="USB3 Video: USB3 Video",
        by_id="usb-UltraSemi_USB3_Video_35562055",
        by_path="platform-3610000.usb-usb-0:1.3:1.0",
        serial="35562055",
        nodos=(("/dev/video2", 0x1), ("/dev/video3", 0x800000)),
        nodos_captura=("/dev/video2",),
        nodo_captura="/dev/video2",
    )
    monkeypatch.setattr(dispositivos, "listar_dispositivos", lambda: [detectado])

    codigo = publicar.main(["--fuente", "capturadora", "--dispositivo", "35562055",
                            "--listar-dispositivos"])
    assert codigo == 0
    assert "/dev/video2[captura]" in capsys.readouterr().out


def test_cli_listar_dispositivos_sin_v4l2(monkeypatch, capsys):
    from ocr import publicar
    import ocr.dispositivos as dispositivos

    def listar_roto():
        raise RuntimeError("La resolución por identidad requiere Linux/V4L2")

    monkeypatch.setattr(dispositivos, "listar_dispositivos", listar_roto)
    assert publicar.main(["--listar-dispositivos"]) == 1
    assert "Linux/V4L2" in capsys.readouterr().out


def test_descarta_los_frames_de_arranque(captura):
    fuente = FuenteCapturadora("/dev/video0", frames_de_arranque=15)
    # 15 descartados + (grab+read) de la validación de resolución = 17 al abrir
    assert captura[0].n_lecturas == 17
    primero = fuente.frame()                      # grab (18) + read (19)
    assert primero[0, 0, 0] == captura[0].n_lecturas % 256
    assert captura[0].n_lecturas == 19


def test_devuelve_bgr_y_cambio_siempre_true(captura):
    fuente = FuenteCapturadora("/dev/video0")
    frame = fuente.frame()
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (ALTO, ANCHO, 3)
    assert frame.dtype == np.uint8
    assert fuente.cambio() is True
    assert fuente.cambio() is True                # no se consume, es video en vivo


def test_dispositivo_que_no_abre_da_error_claro(captura, monkeypatch):
    def fabrica_cerrada(dispositivo, preferencia=None):
        instancia = CapturaFalsa(dispositivo, preferencia)
        instancia.abierta = False
        captura.append(instancia)
        return instancia

    monkeypatch.setattr("ocr.fuente.cv2.VideoCapture", fabrica_cerrada)
    with pytest.raises(ValueError, match="No se pudo abrir"):
        FuenteCapturadora("/dev/video9")
    assert captura[-1].liberada is True           # no queda el handle colgado


def test_resolucion_distinta_da_error_accionable(captura, monkeypatch):
    def fabrica_hd(dispositivo, preferencia=None):
        instancia = CapturaFalsa(dispositivo, preferencia)
        instancia.plan = lambda n: (True, _frame(n, ancho=1280, alto=720))
        captura.append(instancia)
        return instancia

    monkeypatch.setattr("ocr.fuente.cv2.VideoCapture", fabrica_hd)
    with pytest.raises(ValueError, match="1280x720.*1920x1080"):
        FuenteCapturadora("/dev/video0")
    assert captura[-1].liberada is True


def test_fallo_transitorio_se_reintenta(captura):
    fuente = FuenteCapturadora("/dev/video0")
    fallos = {"restantes": 2}

    def plan(n):
        if fallos["restantes"] > 0:
            fallos["restantes"] -= 1
            return False, None
        return True, _frame(n)

    captura[0].plan = plan
    frame = fuente.frame()                        # intento 1 falla, el 2 sirve
    # el frame servido es el último consumido (read del intento que triunfó)
    assert frame[0, 0, 0] == captura[0].n_lecturas % 256
    assert fallos["restantes"] == 0


def test_fallo_persistente_lanza_y_nunca_sirve_frame_viejo(captura):
    fuente = FuenteCapturadora("/dev/video0", reintentos_lectura=3)
    bueno = fuente.frame()                        # hay un frame bueno reciente
    assert bueno is not None
    captura[0].plan = lambda n: (False, None)     # la capturadora muere
    with pytest.raises(RuntimeError, match="dejó de entregar frames"):
        fuente.frame()
    # y el intento posterior tampoco "recuerda" el frame bueno anterior
    with pytest.raises(RuntimeError):
        fuente.frame()


def test_cerrar_libera_y_es_idempotente(captura):
    fuente = FuenteCapturadora("/dev/video0")
    fuente.cerrar()
    assert captura[0].liberada is True
    fuente.cerrar()                               # segundo cierre: no lanza
    with pytest.raises(RuntimeError, match="cerrada"):
        fuente.frame()                            # tras cerrar no hay frames


def test_cli_construye_la_capturadora(monkeypatch, capsys):
    """--fuente capturadora --dispositivo X llega a FuenteCapturadora(X)."""
    from ocr import publicar

    construidas = []

    class FuenteStub:
        def __init__(self, dispositivo):
            construidas.append(dispositivo)

        def frame(self):
            raise AssertionError("no debería leerse en este test")

        def cambio(self):
            return True

        def cerrar(self):
            pass

    monkeypatch.setattr(publicar, "FuenteCapturadora", FuenteStub)
    monkeypatch.setattr(publicar, "correr", lambda *a, **k: None)
    codigo = publicar.main(["--fuente", "capturadora", "--dispositivo", "/dev/video7",
                            "--motor", "plantilla", "--solo-consola"])
    assert codigo == 0
    assert construidas == ["/dev/video7"]


def test_cli_error_de_capturadora_sale_limpio(monkeypatch, capsys):
    from ocr import publicar

    class FuenteRota:
        def __init__(self, dispositivo):
            raise ValueError(f"No se pudo abrir la capturadora {dispositivo!r}")

    monkeypatch.setattr(publicar, "FuenteCapturadora", FuenteRota)
    codigo = publicar.main(["--fuente", "capturadora", "--motor", "plantilla",
                            "--solo-consola"])
    assert codigo == 1
    assert "No se pudo abrir" in capsys.readouterr().out


class FuenteAbierta:
    """Stub de FuenteCapturadora que abre bien y registra si fue liberada."""

    ultima = None

    def __init__(self, dispositivo):
        self.cerrada = False
        FuenteAbierta.ultima = self

    def frame(self):
        raise AssertionError("no debería leerse: el arranque falla antes")

    def cambio(self):
        return True

    def cerrar(self):
        self.cerrada = True


@pytest.mark.parametrize("caso", ["perfil_inexistente", "motor_sin_rapidocr", "broker_caido"])
def test_capturadora_se_libera_si_el_arranque_falla_despues_de_abrirla(monkeypatch, capsys, caso):
    """La garantía titular de la iteración: si algo falla DESPUÉS de abrir la
    capturadora (perfil, motor, broker), el dispositivo se libera y el CLI sale
    limpio con código 1 — nunca queda /dev/video0 ocupado por un arranque roto."""
    import sys as _sys

    from ocr import publicar

    monkeypatch.setattr(publicar, "FuenteCapturadora", FuenteAbierta)
    FuenteAbierta.ultima = None
    argv = ["--fuente", "capturadora", "--motor", "plantilla", "--solo-consola"]

    if caso == "perfil_inexistente":
        argv += ["--perfil", "no_existe_este_perfil.json"]
    elif caso == "motor_sin_rapidocr":
        monkeypatch.setitem(_sys.modules, "rapidocr_onnxruntime", None)
        monkeypatch.delitem(_sys.modules, "ocr.motor.rapid", raising=False)
        argv = ["--fuente", "capturadora", "--motor", "produccion", "--solo-consola"]
    else:  # broker_caido
        def broker_roto(*a, **k):
            raise OSError("conexión rechazada")
        monkeypatch.setattr(publicar, "crear_cliente_mqtt", broker_roto)
        argv = ["--fuente", "capturadora", "--motor", "plantilla"]  # sin --solo-consola

    codigo = publicar.main(argv)
    assert codigo == 1
    assert "ERROR" in capsys.readouterr().out
    assert FuenteAbierta.ultima is not None, "la fuente ni siquiera se construyó"
    assert FuenteAbierta.ultima.cerrada is True
