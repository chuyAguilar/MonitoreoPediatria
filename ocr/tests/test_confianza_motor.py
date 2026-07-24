"""La confianza que devuelve el motor debe respetar el dominio [0, 1].

El umbral de confianza es la salvaguarda principal del módulo y se aplica como
`confianza < umbral`. Si un motor mal cableado devolviera otra escala (0–100)
o un NaN, esa comparación sería falsa para todo y la puerta quedaría abierta en
silencio. Como el motor es intercambiable por diseño, el lector no puede fiarse:
tiene que validar lo que recibe.
"""

import pytest

from ocr.lector import leer_imagen
from ocr.mock import generar_mock
from ocr.motor.base import LectorOCR
from ocr.perfiles import perfil_desde_dict

SIGNOS_SIMPLES = ("fc", "spo2", "fp", "fr", "temp")


class MotorConConfianza(LectorOCR):
    """Motor de prueba: siempre lee bien, pero informa la confianza que se le diga."""

    def __init__(self, confianza, texto="142"):
        self.confianza = confianza
        self.texto = texto

    def leer(self, imagen):
        return self.texto, self.confianza


@pytest.fixture(scope="module")
def perfil_mock():
    return perfil_desde_dict(generar_mock.derivar_perfil())


@pytest.fixture(scope="module")
def imagen():
    return generar_mock.generar_imagen()


@pytest.mark.parametrize("confianza, caso", [
    (75.0, "escala 0-100: un 75 % se colaría como si fuera 75 veces el máximo"),
    (7.5, "fuera de dominio por arriba"),
    (float("nan"), "NaN: toda comparación con él es falsa"),
    (float("inf"), "infinito"),
    (None, "el motor no informó confianza"),
    ("0.9", "confianza como texto: incumple la interfaz aunque el número sea válido"),
    (True, "booleano: colaría como 1.0, la confianza máxima"),
])
def test_confianza_fuera_de_dominio_no_publica(perfil_mock, imagen, confianza, caso):
    mensaje = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01",
                          motor=MotorConConfianza(confianza))
    for clave in SIGNOS_SIMPLES:
        assert mensaje["signos"][clave]["valor"] is None, caso
        assert mensaje["signos"][clave]["confianza"] == 0.0
    assert mensaje["signos"]["pni"] is None


def test_confianza_valida_sigue_publicando(perfil_mock, imagen):
    """El camino feliz no debe romperse por validar el dominio."""
    mensaje = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01",
                          motor=MotorConConfianza(0.95))
    assert mensaje["signos"]["fc"]["valor"] == 142
    assert mensaje["signos"]["fc"]["confianza"] == 0.95


def test_no_se_recorta_al_rango(perfil_mock, imagen):
    """Una confianza de 7.5 se descarta, no se convierte en 1.0.

    Recortarla haría pasar por óptima la peor lectura posible, que es el
    resultado exactamente opuesto al que se busca.
    """
    mensaje = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01",
                          motor=MotorConConfianza(7.5))
    assert mensaje["signos"]["fc"]["confianza"] == 0.0


def test_ninguna_confianza_emitida_sale_del_contrato(perfil_mock, imagen):
    """El contrato 1.1 documenta confianza en 0–1: debe cumplirse siempre."""
    for confianza in (0.0, 0.5, 1.0, 75.0, float("nan"), None):
        mensaje = leer_imagen(imagen, perfil_mock, "cama-01", "jetson-01",
                              motor=MotorConConfianza(confianza))
        for clave in SIGNOS_SIMPLES:
            assert 0.0 <= mensaje["signos"][clave]["confianza"] <= 1.0
        pni = mensaje["signos"]["pni"]
        if pni is not None:
            assert 0.0 <= pni["confianza"] <= 1.0
