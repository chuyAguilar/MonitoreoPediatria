"""Forma del mensaje: claves, unidades y formatos del contrato 1.1."""

import re

from ocr.lector import leer_imagen
from ocr.mock import generar_mock

RE_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_estructura_del_mensaje(perfil_mock, motor):
    imagen = generar_mock.generar_imagen()
    mensaje = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)

    assert set(mensaje) == {"contrato", "cama_id", "device_id", "ts", "origen", "signos"}
    assert mensaje["contrato"] == "1.1"
    assert mensaje["origen"] == "ocr"
    assert RE_TS.match(mensaje["ts"])

    signos = mensaje["signos"]
    assert set(signos) == {"fc", "spo2", "fp", "fr", "temp", "pni"}

    unidades = {"fc": "lpm", "spo2": "%", "fp": "lpm", "fr": "rpm", "temp": "C"}
    for clave, unidad in unidades.items():
        assert set(signos[clave]) == {"valor", "unidad", "confianza"}
        assert signos[clave]["unidad"] == unidad
        assert 0.0 <= signos[clave]["confianza"] <= 1.0

    pni = signos["pni"]
    assert set(pni) == {"sis", "dia", "media", "unidad", "ts", "confianza"}
    assert pni["unidad"] == "mmHg"
    assert RE_TS.match(pni["ts"])
    assert 0.0 <= pni["confianza"] <= 1.0


def test_valor_null_lleva_confianza_cero(perfil_mock, motor):
    imagen = generar_mock.generar_imagen({"fr": None})
    signos = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["fr"] == {"valor": None, "unidad": "rpm", "confianza": 0.0}
