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
