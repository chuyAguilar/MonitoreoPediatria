"""Reglas de robustez: fuera de rango o ilegible → null + confianza 0."""

import cv2

from ocr.lector import leer_imagen
from ocr.mock import generar_mock


def test_fuera_de_rango_produce_null(perfil_mock, motor):
    # 999 es dibujable (3 dígitos) pero fisiológicamente implausible
    imagen = generar_mock.generar_imagen({"fc": 999})
    signos = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["fc"]["valor"] is None
    assert signos["fc"]["confianza"] == 0.0
    # El resto de la imagen se sigue leyendo bien
    assert signos["spo2"]["valor"] == 97


def test_roi_ilegible_produce_null(perfil_mock, motor):
    # Rayas sobre la ROI de FC: hay tinta pero no son dígitos
    imagen = generar_mock.generar_imagen()
    x, y, w, h = perfil_mock.signos["fc"].roi
    cv2.rectangle(imagen, (x, y), (x + w - 1, y + h - 1), (12, 12, 12), -1)
    for dx in range(-h, w, 14):
        cv2.line(imagen, (x + dx, y), (x + dx + h, y + h - 1), (255, 255, 255), 2)
    signos = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["fc"]["valor"] is None
    assert signos["fc"]["confianza"] == 0.0
    assert signos["spo2"]["valor"] == 97


def test_signo_apagado_produce_null(perfil_mock, motor):
    imagen = generar_mock.generar_imagen({"temp": None})
    signos = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["temp"]["valor"] is None
    assert signos["temp"]["confianza"] == 0.0


def test_pni_parcial_se_anula_completa(perfil_mock, motor):
    """Nunca una presión parcial: si falta un componente, pni entera es null."""
    imagen = generar_mock.generar_imagen({"pni_dia": None})
    signos = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None
    # Los signos no relacionados no se ven afectados
    assert signos["fc"]["valor"] == 142


def test_pni_totalmente_ausente_es_null(perfil_mock, motor):
    imagen = generar_mock.generar_imagen(
        {"pni_sis": None, "pni_dia": None, "pni_media": None}
    )
    signos = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None
