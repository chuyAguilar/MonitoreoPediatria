"""Publicador MQTT con un cliente FALSO: sin broker, sin red, sin motor real.

Verifica los topics, el payload del contrato, QoS/retain y el ciclo
online/offline. Usa el motor de plantilla, así que no necesita el motor de
producción (RapidOCR).
"""

import json
from pathlib import Path

import pytest

import ocr
from ocr.fuente import FuenteImagenFija
from ocr.motor.plantilla import LectorPlantilla
from ocr.perfiles import cargar_perfil
from ocr.publicador import PublicadorOCR
from ocr.publicar import correr

FRAME = Path(ocr.__file__).parent / "perfiles" / "simcore" / "frame_simcore.png"
PERFIL = Path(ocr.__file__).parent / "perfiles" / "simcore" / "simcore.json"


class ClienteFalso:
    """Registra cada publish; imita loop_stop/disconnect sin hacer nada."""

    def __init__(self):
        self.publicaciones = []  # lista de (topic, payload, qos, retain)
        self.desconectado = False

    def publish(self, topic, payload, qos=0, retain=False):
        self.publicaciones.append((topic, payload, qos, retain))

    def loop_stop(self):
        pass

    def disconnect(self):
        self.desconectado = True

    # atajos de consulta
    def de_topic(self, topic):
        return [p for p in self.publicaciones if p[0] == topic]


@pytest.fixture()
def cliente():
    return ClienteFalso()


@pytest.fixture()
def publicador(cliente):
    return PublicadorOCR("cama-01", "jetson-01", cliente)


def test_publicar_vitales_topic_y_qos(publicador, cliente):
    mensaje = {"contrato": "1.1", "cama_id": "cama-01", "signos": {"fc": {"valor": 142}}}
    publicador.publicar_vitales(mensaje)
    (topic, payload, qos, retain), = cliente.publicaciones
    assert topic == "monitoreo/vitales/cama-01"
    assert qos == 1 and retain is True
    assert json.loads(payload) == mensaje  # se publica el contrato TAL CUAL


def test_publicar_estado_formato(publicador, cliente):
    publicador.publicar_estado("online")
    (topic, payload, qos, retain), = cliente.publicaciones
    assert topic == "monitoreo/estado/cama-01"
    assert qos == 1 and retain is True
    datos = json.loads(payload)
    assert datos["cama_id"] == "cama-01"
    assert datos["device_id"] == "jetson-01"
    assert datos["estado"] == "online"
    assert datos["ts"].endswith("Z")


def test_cerrar_publica_offline_y_desconecta(publicador, cliente):
    publicador.cerrar()
    assert cliente.desconectado is True
    estados = [json.loads(p[1])["estado"] for p in cliente.de_topic("monitoreo/estado/cama-01")]
    assert estados == ["offline"]


# --- Ciclo de vida completo con el bucle, sin broker ni motor real --------


@pytest.fixture()
def perfil_simcore():
    return cargar_perfil(PERFIL)


def _correr_n(cliente, perfil, n):
    fuente = FuenteImagenFija(FRAME)
    publicador = PublicadorOCR("cama-01", "jetson-01", cliente)
    correr(fuente, LectorPlantilla(), perfil, "cama-01", "jetson-01",
           publicador, hz=1000.0, max_ticks=n)


def test_ciclo_online_vitales_offline(cliente, perfil_simcore):
    _correr_n(cliente, perfil_simcore, 2)

    vitales = cliente.de_topic("monitoreo/vitales/cama-01")
    estados = cliente.de_topic("monitoreo/estado/cama-01")

    assert len(vitales) == 2                        # dos ticks
    # online es la PRIMERA publicación de estado; offline la ÚLTIMA
    assert json.loads(estados[0][1])["estado"] == "online"
    assert json.loads(estados[-1][1])["estado"] == "offline"
    # online se publica antes que el primer vital; offline después del último
    assert cliente.publicaciones[0][0] == "monitoreo/estado/cama-01"
    assert cliente.publicaciones[-1][0] == "monitoreo/estado/cama-01"


def test_publica_los_null_sin_rellenar(cliente, perfil_simcore):
    """Con el andamiaje sobre SimCore los valores van null: el transporte los pasa tal cual."""
    _correr_n(cliente, perfil_simcore, 1)
    vital = cliente.de_topic("monitoreo/vitales/cama-01")[0]
    mensaje = json.loads(vital[1])
    assert mensaje["contrato"] == "1.1"
    assert mensaje["origen"] == "ocr"
    # el motor de plantilla no lee la tipografía real: todo null, pero estructura válida
    assert mensaje["signos"]["fc"]["valor"] is None
    assert mensaje["signos"]["pni"] is None
    assert set(mensaje["signos"]) == {"fc", "spo2", "fp", "fr", "temp", "pni"}


def test_ts_de_cabecera_se_refresca_en_cada_publicacion(cliente, perfil_simcore, monkeypatch):
    """La imagen no cambia (OCR una vez), pero cada publicación re-sella el ts.

    Se controla el reloj para que discrimine: si el bucle reusara el ts de la
    única lectura en vez de re-sellarlo, los tres saldrían iguales y el test
    fallaría (los ticks reales caen en el mismo segundo, por eso hace falta).
    """
    n = {"i": 0}

    def reloj_falso():
        n["i"] += 1
        return f"2026-07-28T00:00:{n['i']:02d}Z"

    monkeypatch.setattr("ocr.publicar.ahora_iso", reloj_falso)
    _correr_n(cliente, perfil_simcore, 3)
    ts = [json.loads(p[1])["ts"] for p in cliente.de_topic("monitoreo/vitales/cama-01")]
    assert len(ts) == 3
    assert len(set(ts)) == 3          # tres ts DISTINTOS (se re-selló cada vez)
    assert ts == sorted(ts)           # y crecientes


def test_solo_se_ocr_a_una_vez_con_imagen_fija(cliente, perfil_simcore):
    """La fuente fija dice cambio()=True solo una vez → una sola lectura OCR."""
    fuente = FuenteImagenFija(FRAME)
    lecturas = {"n": 0}
    motor = LectorPlantilla()
    leer_real = motor.leer

    def contar(imagen):
        lecturas["n"] += 1
        return leer_real(imagen)

    motor.leer = contar
    publicador = PublicadorOCR("cama-01", "jetson-01", cliente)
    correr(fuente, motor, perfil_simcore, "cama-01", "jetson-01",
           publicador, hz=1000.0, max_ticks=4)

    # 6 ROIs distintas leídas UNA vez (no 4x6): no se re-OCR-a la imagen fija
    assert lecturas["n"] == 6
    assert len(cliente.de_topic("monitoreo/vitales/cama-01")) == 4


# --- Last Will (ADR-022) ---------------------------------------------------


def _stub_paho(monkeypatch, clase_client):
    """Stub del paquete paho COMPLETO (tres claves de sys.modules).

    `import paho.mqtt.client as mqtt` resuelve el binding `as` por getattr
    sobre el paquete PADRE (Python >=3.7): stubear solo 'paho.mqtt.client'
    falla con ImportError o — si otro test ya importó el paho real — cuela el
    módulo REAL en silencio según el orden de la suite. Por eso se stubean
    'paho', 'paho.mqtt' y 'paho.mqtt.client' con atributos encadenados.
    """
    import sys
    import types

    stub_paho = types.ModuleType("paho")
    stub_mqtt = types.ModuleType("paho.mqtt")
    stub_client = types.ModuleType("paho.mqtt.client")
    stub_paho.mqtt = stub_mqtt
    stub_mqtt.client = stub_client
    stub_client.Client = clase_client
    stub_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2="v2")
    monkeypatch.setitem(sys.modules, "paho", stub_paho)
    monkeypatch.setitem(sys.modules, "paho.mqtt", stub_mqtt)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", stub_client)


class ClienteEspia:
    """Registra el ORDEN de configuración del cliente real."""

    instancias = []

    def __init__(self, version, client_id=None):
        self.version = version
        self.client_id = client_id
        self.llamadas = []
        self.will = None
        self.on_connect = None
        self.on_disconnect = None
        self.keepalive = None
        self.reconexion = None
        self.on_connect_al_conectar = "no-registrado"
        ClienteEspia.instancias.append(self)

    def will_set(self, topic, payload, qos=0, retain=False):
        self.llamadas.append("will_set")
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay, max_delay):
        self.llamadas.append("reconnect_delay_set")
        self.reconexion = (min_delay, max_delay)

    def connect(self, broker, puerto, keepalive=60):
        self.llamadas.append("connect")
        self.keepalive = keepalive
        # snapshot: ¿el callback ya estaba asignado AL conectar?
        self.on_connect_al_conectar = self.on_connect

    def loop_start(self):
        self.llamadas.append("loop_start")


@pytest.fixture(autouse=True)
def _limpiar_espias():
    ClienteEspia.instancias = []
    yield
    ClienteEspia.instancias = []


def test_crear_cliente_con_will_orden_y_flags(monkeypatch):
    from ocr.publicador import (
        KEEPALIVE_S,
        al_conectar_republica_online,
        crear_cliente_mqtt,
        will_de_estado,
    )

    _stub_paho(monkeypatch, ClienteEspia)
    cb = al_conectar_republica_online("cama-01", "jetson-01")
    crear_cliente_mqtt("broker-x", 1883, "ocr-cama-01",
                       will=will_de_estado("cama-01", "jetson-01"),
                       al_conectar=cb)
    (espia,) = ClienteEspia.instancias
    assert espia.version == "v2" and espia.client_id == "ocr-cama-01"
    topic, payload, qos, retain = espia.will
    assert topic == "monitoreo/estado/cama-01"
    assert qos == 1 and retain is True
    assert json.loads(payload)["estado"] == "offline"
    # el orden que importa: will y callback ANTES de connect, loop al final
    assert espia.llamadas.index("will_set") < espia.llamadas.index("connect")
    assert espia.on_connect_al_conectar is cb
    assert espia.llamadas[-1] == "loop_start"
    assert espia.keepalive == KEEPALIVE_S
    assert espia.reconexion == (1, 30)
    from ocr.publicador import _al_desconectar
    assert espia.on_disconnect is _al_desconectar


def test_crear_cliente_sin_will_retrocompatible(monkeypatch):
    from ocr.publicador import KEEPALIVE_S, _al_desconectar, crear_cliente_mqtt

    _stub_paho(monkeypatch, ClienteEspia)
    crear_cliente_mqtt("broker-x", 1883, "ocr-cama-01")
    (espia,) = ClienteEspia.instancias
    assert "will_set" not in espia.llamadas
    assert espia.on_connect is None
    assert espia.llamadas[-1] == "loop_start"
    # el blindaje NO depende de pasar will: keepalive/reconexión/log siempre
    assert espia.keepalive == KEEPALIVE_S
    assert espia.reconexion == (1, 30)
    assert espia.on_disconnect is _al_desconectar


def test_crear_cliente_sin_paho_error_accionable(monkeypatch):
    import sys

    from ocr.publicador import crear_cliente_mqtt

    monkeypatch.setitem(sys.modules, "paho", None)  # simula ausencia
    monkeypatch.delitem(sys.modules, "paho.mqtt", raising=False)
    monkeypatch.delitem(sys.modules, "paho.mqtt.client", raising=False)
    with pytest.raises(RuntimeError, match="Falta paho-mqtt"):
        crear_cliente_mqtt("broker-x", 1883, "ocr-cama-01")


def test_al_desconectar_loguea_y_avisa_takeover(capsys):
    from ocr import publicador

    publicador._al_desconectar(None, None, None, "timeout", None)
    assert "desconectado del broker" in capsys.readouterr().out
    # dos desconexiones inmediatas tras conectar -> sospecha de takeover
    publicador._conectado_desde = __import__("time").monotonic()
    publicador._desconexiones_rapidas = 0
    publicador._al_desconectar(None, None, None, "takeover", None)
    publicador._al_desconectar(None, None, None, "takeover", None)
    assert "mismo client_id" in capsys.readouterr().out
    publicador._conectado_desde = None
    publicador._desconexiones_rapidas = 0


def test_cerrar_desarma_on_connect_antes_de_la_ventana():
    # Sin el desarme, una reconexión durante el sleep del apagado
    # re-publicaría "online" retenido para una cama APAGADA — y el disconnect
    # limpio no dispara el will que lo corrija.
    from ocr.publicador import PublicadorOCR

    class ClienteConCallback(ClienteFalso):
        def __init__(self):
            super().__init__()
            self.on_connect = lambda *a: None
            self.on_connect_al_desconectar = "no-registrado"

        def disconnect(self):
            self.on_connect_al_desconectar = self.on_connect
            super().disconnect()

    cliente = ClienteConCallback()
    PublicadorOCR("cama-01", "jetson-01", cliente).cerrar()
    assert cliente.on_connect is None
    assert cliente.on_connect_al_desconectar is None, \
        "el desarme debe ocurrir ANTES de cortar (la ventana del sleep)"


def test_will_mismo_formato_que_publicar_estado(publicador, cliente):
    from ocr.publicador import will_de_estado

    publicador.publicar_estado("offline")
    (_, payload_cerrar, _, _), = cliente.publicaciones
    _, payload_will = will_de_estado("cama-01", "jetson-01")
    normal = json.loads(payload_cerrar)
    will = json.loads(payload_will)
    # mismo formato POR CONSTRUCCIÓN: mismas claves, mismos valores (ts aparte:
    # el del will es el instante de conexión — caveat de ADR-022)
    assert set(will) == set(normal)
    for clave in ("cama_id", "device_id", "estado"):
        assert will[clave] == normal[clave]
    assert will["ts"].endswith("Z")  # el contrato exige sufijo Z, estricto


class _CodigoConexion:
    def __init__(self, es_fallo):
        self.is_failure = es_fallo

    def __str__(self):
        return "Not authorized" if self.is_failure else "Success"


def test_al_conectar_republica_online(cliente):
    from ocr.publicador import al_conectar_republica_online

    cb = al_conectar_republica_online("cama-01", "jetson-01")
    # la firma VERSION2 real: 5 argumentos posicionales (lección ito-10)
    cb(cliente, None, None, _CodigoConexion(es_fallo=False), None)
    (topic, payload, qos, retain), = cliente.publicaciones
    assert topic == "monitoreo/estado/cama-01"
    assert qos == 1 and retain is True
    datos = json.loads(payload)
    assert datos["estado"] == "online" and datos["device_id"] == "jetson-01"


def test_al_conectar_connack_fallido_no_publica(cliente, capsys):
    from ocr.publicador import al_conectar_republica_online

    cb = al_conectar_republica_online("cama-01", "jetson-01")
    cb(cliente, None, None, _CodigoConexion(es_fallo=True), None)
    assert cliente.publicaciones == []
    assert "rechazada" in capsys.readouterr().out


def test_al_conectar_reason_sin_is_failure_no_revienta(cliente):
    from ocr.publicador import al_conectar_republica_online

    cb = al_conectar_republica_online("cama-01", "jetson-01")
    cb(cliente, None, None, object(), None)  # duck-typing: publica igual
    assert len(cliente.publicaciones) == 1


def test_al_conectar_excepcion_no_propaga(capsys):
    # Una excepción del callback mataría el hilo de red de paho sin
    # reconexión (ADR-021/022): el blindaje debe tragarla con log.
    from ocr.publicador import al_conectar_republica_online

    class ClienteQueRevienta:
        def publish(self, *a, **k):
            raise RuntimeError("boom")

    cb = al_conectar_republica_online("cama-01", "jetson-01")
    cb(ClienteQueRevienta(), None, None, _CodigoConexion(es_fallo=False), None)
    assert "error en on_connect" in capsys.readouterr().out


def test_cli_cablea_el_will_con_la_cama_de_args(monkeypatch):
    # El fake captura los kwargs y lanza OSError: main sale con 1 sin entrar
    # al bucle infinito (patrón de test_fuente_capturadora).
    from ocr import publicar

    capturado = {}

    def fake_crear(broker, puerto, client_id, will=None, al_conectar=None):
        capturado.update(will=will, al_conectar=al_conectar, client_id=client_id)
        raise OSError("sin broker (test)")

    monkeypatch.setattr(publicar, "crear_cliente_mqtt", fake_crear)
    assert publicar.main(["--cama-id", "cama-07", "--device-id", "jetson-02",
                          "--motor", "plantilla"]) == 1
    topic, payload = capturado["will"]
    assert topic == "monitoreo/estado/cama-07"
    datos = json.loads(payload)
    assert datos == {**datos, "cama_id": "cama-07", "device_id": "jetson-02",
                     "estado": "offline"}
    assert callable(capturado["al_conectar"])
    assert capturado["client_id"] == "ocr-cama-07"


def test_cli_falla_limpio_sin_motor_real_en_solo_consola(monkeypatch):
    """--solo-consola sin el motor de producción sale con código 1, no un traceback."""
    import sys

    from ocr import publicar

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)  # simula ausencia
    monkeypatch.delitem(sys.modules, "ocr.motor.rapid", raising=False)
    # motor por defecto = produccion; --solo-consola no debería exigir el motor real
    assert publicar.main(["--solo-consola"]) == 1


def test_cli_solo_consola_con_plantilla_es_valido(monkeypatch, capsys):
    """Con --motor plantilla, --solo-consola no necesita el motor real (sale 0)."""
    import sys

    from ocr import publicar

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    # el bucle es infinito; lo acotamos parcheando correr para 1 tick
    real_correr = publicar.correr
    monkeypatch.setattr(publicar, "correr",
                        lambda *a, **k: real_correr(*a, **{**k, "max_ticks": 1}))
    assert publicar.main(["--solo-consola", "--motor", "plantilla", "--hz", "1000"]) == 0
