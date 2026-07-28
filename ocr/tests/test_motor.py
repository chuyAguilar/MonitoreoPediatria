"""Tests del motor de plantilla y del preprocesamiento, sin pasar por el lector.

Desde la iteración 3 (ADR-016) el lector entrega a los motores el recorte CRUDO
(color) y cada motor preprocesa a su gusto; el de plantilla binariza adentro.
Estos tests le pasan imágenes dibujadas (grises) o recortes en color: ambos son
entradas válidas del nuevo contrato, y el motor las binariza internamente.
"""

import numpy as np
import pytest

from ocr import digitos, preproceso


@pytest.mark.parametrize("caracter", list("0123456789"))
def test_lee_cada_digito(motor, caracter):
    binaria = digitos.dibujar_numero(caracter, 80)
    texto, confianza = motor.leer(binaria)
    assert texto == caracter
    assert confianza >= 0.9


def test_lee_un_recorte_en_color(motor):
    """El contrato de la iteración 3: el motor acepta el recorte crudo (BGR).

    Número claro sobre fondo oscuro, como en un monitor; el motor binariza
    internamente y lo lee igual que si le pasaran la binaria.
    """
    binaria = digitos.dibujar_numero("142", 80)
    color = np.full((binaria.shape[0] + 20, binaria.shape[1] + 20, 3), 12, dtype=np.uint8)
    region = color[10:10 + binaria.shape[0], 10:10 + binaria.shape[1]]
    region[binaria > 0] = (80, 255, 80)
    texto, confianza = motor.leer(color)
    assert texto == "142"
    assert confianza >= 0.9


def test_lee_numero_con_punto_decimal(motor):
    binaria = digitos.dibujar_numero("36.9", 80)
    texto, confianza = motor.leer(binaria)
    assert texto == "36.9"
    assert confianza >= 0.9


def test_lee_el_separador_de_campo_combinado(motor):
    """La barra debe reconocerse para poder partir una PNI "SIS/DIA".

    Puntúa algo por debajo de un dígito (su diagonal se rasteriza en escalera),
    pero muy por encima del umbral de aceptación del lector.
    """
    binaria = digitos.dibujar_numero("120/75", 80)
    texto, confianza = motor.leer(binaria)
    assert texto == "120/75"
    assert confianza >= 0.8


def test_la_barra_no_se_confunde_con_un_digito(motor):
    """Un número sin barra no debe producirla (inventaría una presión)."""
    texto, _ = motor.leer(digitos.dibujar_numero("12075", 80))
    assert texto == "12075"
    assert "/" not in texto


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
