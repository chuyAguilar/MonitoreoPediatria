"""Fuente de frames desacoplada."""

from pathlib import Path

import numpy as np
import pytest

import ocr
from ocr.fuente import FuenteImagenFija

FRAME = Path(ocr.__file__).parent / "perfiles" / "simcore" / "frame_simcore.png"


def test_lee_el_frame_una_vez_y_devuelve_lo_mismo():
    fuente = FuenteImagenFija(FRAME)
    a = fuente.frame()
    b = fuente.frame()
    assert a is b  # mismo arreglo cacheado, no re-lee el disco
    assert a.shape == (1080, 1920, 3)


def test_cambio_es_true_solo_la_primera_vez():
    """Una imagen fija no cambia: OCR una vez, luego republicar."""
    fuente = FuenteImagenFija(FRAME)
    assert fuente.cambio() is True
    assert fuente.cambio() is False
    assert fuente.cambio() is False


def test_archivo_inexistente_da_error_claro():
    with pytest.raises(ValueError, match="No se pudo leer"):
        FuenteImagenFija("no_existe_este_frame.png")


def test_cerrar_no_falla():
    FuenteImagenFija(FRAME).cerrar()  # no-op, no debe lanzar
