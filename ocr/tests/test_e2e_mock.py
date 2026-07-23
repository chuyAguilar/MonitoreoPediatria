"""Pipeline completo: imagen mock → lector → mensaje del contrato 1.1."""

import json
from pathlib import Path

import ocr
from ocr.lector import leer_imagen
from ocr.mock import generar_mock

CONFIANZA_MINIMA = 0.8


def test_lee_los_valores_conocidos(perfil_mock, motor):
    imagen = generar_mock.generar_imagen()
    mensaje = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)
    signos = mensaje["signos"]

    assert signos["fc"]["valor"] == 142
    assert signos["spo2"]["valor"] == 97
    assert signos["fp"]["valor"] == 141
    assert signos["fr"]["valor"] == 48
    assert signos["temp"]["valor"] == 36.9
    for clave in ("fc", "spo2", "fp", "fr", "temp"):
        assert signos[clave]["confianza"] >= CONFIANZA_MINIMA

    assert signos["pni"] is not None
    assert signos["pni"]["sis"] == 66
    assert signos["pni"]["dia"] == 39
    assert signos["pni"]["media"] == 48
    assert signos["pni"]["confianza"] >= CONFIANZA_MINIMA


def test_cabecera_parametrizada(perfil_mock, motor):
    imagen = generar_mock.generar_imagen()
    mensaje = leer_imagen(
        imagen, perfil_mock, "cama-07", "jetson-02", motor=motor,
        ts="2026-07-22T00:00:00Z",
    )
    assert mensaje["contrato"] == "1.1"
    assert mensaje["origen"] == "ocr"
    assert mensaje["cama_id"] == "cama-07"
    assert mensaje["device_id"] == "jetson-02"
    assert mensaje["ts"] == "2026-07-22T00:00:00Z"
    # En imagen fija la PNI hereda el ts del mensaje (ver TODO en ocr/contrato.py)
    assert mensaje["signos"]["pni"]["ts"] == "2026-07-22T00:00:00Z"


def test_perfil_en_disco_sincronizado_con_el_generador():
    """El JSON commiteado debe ser exactamente el que deriva el generador."""
    ruta = Path(ocr.__file__).parent / "perfiles" / "monitor_mock.json"
    en_disco = json.loads(ruta.read_text(encoding="utf-8"))
    assert en_disco == generar_mock.derivar_perfil()
