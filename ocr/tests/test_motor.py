"""Tests del motor de plantilla y del preprocesamiento, sin pasar por el lector."""

import numpy as np
import pytest

from ocr import digitos, preproceso


@pytest.mark.parametrize("caracter", list("0123456789"))
def test_lee_cada_digito(motor, caracter):
    binaria = digitos.dibujar_numero(caracter, 80)
    texto, confianza = motor.leer(binaria)
    assert texto == caracter
    assert confianza >= 0.9


def test_lee_numero_con_punto_decimal(motor):
    binaria = digitos.dibujar_numero("36.9", 80)
    texto, confianza = motor.leer(binaria)
    assert texto == "36.9"
    assert confianza >= 0.9


def test_imagen_vacia_no_reconoce(motor):
    texto, confianza = motor.leer(np.zeros((100, 200), dtype=np.uint8))
    assert texto is None
    assert confianza == 0.0


def test_ruido_da_confianza_baja(motor):
    # Rayas diagonales deterministas: hay tinta, pero no son dígitos
    ruido = np.zeros((100, 200), dtype=np.uint8)
    for i in range(0, 200, 12):
        for y in range(100):
            x = (i + y) % 200
            ruido[y, x] = 255
    texto, confianza = motor.leer(ruido)
    if texto is not None:
        assert confianza < 0.6


def test_binarizar_recupera_digitos_de_color():
    # Número cian sobre fondo casi negro, como en el mock
    parche = digitos.dibujar_numero("142", 60)
    lienzo = np.zeros((parche.shape[0] + 20, parche.shape[1] + 20, 3), dtype=np.uint8)
    lienzo[:] = (12, 12, 12)
    region = lienzo[10:10 + parche.shape[0], 10:10 + parche.shape[1]]
    region[parche > 0] = (255, 255, 80)

    binaria = preproceso.binarizar(lienzo)
    assert binaria.shape[0] == preproceso.ALTO_NORMALIZADO
    assert set(np.unique(binaria)) <= {0, 255}


def test_binarizar_roi_sin_contraste_queda_vacia():
    plano = np.full((80, 160, 3), 12, dtype=np.uint8)
    binaria = preproceso.binarizar(plano)
    assert int(np.count_nonzero(binaria)) == 0
