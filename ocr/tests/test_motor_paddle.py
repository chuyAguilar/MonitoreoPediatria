"""Motor ALTERNATIVO PaddleOCR (histórico, ADR-016 → sustituido por ADR-017).

Paddle ya no es el motor de producción (su motor de inferencia segfaultea en
la Jetson aarch64), pero el adaptador se conserva y sigue funcionando en
x86_64. Estos tests se SALTAN si paddleocr no está instalado (su dependencia
ya no se declara en requirements-motor.txt).
"""

import cv2
import numpy as np
import pytest

from ocr import digitos

paddleocr = pytest.importorskip("paddleocr", reason="motor alternativo Paddle no instalado")

from ocr.motor.paddle import LectorPaddleOCR


def _recorte_color(texto, alto=80):
    """Número blanco sobre fondo oscuro, como en un monitor (recorte BGR crudo)."""
    binaria = digitos.dibujar_numero(texto, alto)
    lienzo = np.full((binaria.shape[0] + 30, binaria.shape[1] + 30, 3), 12, dtype=np.uint8)
    region = lienzo[15:15 + binaria.shape[0], 15:15 + binaria.shape[1]]
    region[binaria > 0] = (240, 240, 240)
    return lienzo


@pytest.fixture(scope="module")
def paddle():
    return LectorPaddleOCR()


@pytest.mark.parametrize("texto", ["74", "98", "120/75", "36.8"])
def test_lee_numeros_de_un_recorte_crudo(paddle, texto):
    leido, confianza = paddle.leer(_recorte_color(texto))
    assert leido == texto
    assert 0.0 <= confianza <= 1.0
    assert confianza > 0.6


def test_confianza_siempre_en_dominio(paddle):
    """El adaptador entrega confianza en [0,1]; _confianza_valida es la última red."""
    for texto in ("74", "120/75", "888"):
        _, confianza = paddle.leer(_recorte_color(texto))
        assert 0.0 <= confianza <= 1.0


def test_roi_en_blanco_no_inventa(paddle):
    leido, confianza = paddle.leer(np.full((90, 160, 3), 12, dtype=np.uint8))
    assert leido is None
    assert confianza == 0.0


def test_no_alucina_digitos_de_texto_no_numerico(paddle):
    """Sobre una ROI con letras, el adaptador no debe producir un número válido.

    O devuelve None, o devuelve un texto con letras que el lector rechaza. Lo
    que no puede es inventar dígitos limpios (ver la regla de oro).
    """
    etiqueta = np.full((60, 200, 3), 12, dtype=np.uint8)
    cv2.putText(etiqueta, "NIBP", (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (240, 240, 240), 3, cv2.LINE_AA)
    leido, _ = paddle.leer(etiqueta)
    assert leido is None or not leido.replace(".", "").replace("/", "").isdigit()
