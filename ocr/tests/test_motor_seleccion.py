"""Selección del motor por defecto: falla fuerte, sin fallback silencioso.

Estos tests corren SIEMPRE (no dependen de que el motor real esté instalado):
simulan su ausencia con monkeypatch. La decisión de diseño (ADR-016/017) es
que un sistema de monitoreo que no puede leer debe negarse a arrancar y decir
por qué, no caer en silencio al andamiaje que no lee monitores reales.
"""

import sys

import pytest

from ocr.lector import motor_por_defecto


def _sin_rapidocr(monkeypatch):
    # Hacer que `import rapidocr_onnxruntime` falle, imitando un entorno sin
    # la dependencia, y purgar el módulo del adaptador para forzar re-import.
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    monkeypatch.delitem(sys.modules, "ocr.motor.rapid", raising=False)


def test_falla_fuerte_cuando_el_motor_no_esta_instalado(monkeypatch):
    _sin_rapidocr(monkeypatch)
    with pytest.raises(RuntimeError, match="no instalado"):
        motor_por_defecto()


def test_el_error_es_accionable(monkeypatch):
    """El mensaje debe decir cómo resolverlo y advertir que el andamiaje no sirve."""
    _sin_rapidocr(monkeypatch)
    with pytest.raises(RuntimeError) as exc:
        motor_por_defecto()
    mensaje = str(exc.value)
    assert "RapidOCR" in mensaje
    assert "requirements-motor.txt" in mensaje
    assert "NO lee monitores reales" in mensaje
