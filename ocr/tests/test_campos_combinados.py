"""Andamiaje de la iteración 2 probado con dígitos DIBUJADOS.

Estos tests validan campo combinado (PNI "120/75"), signo ausente y caché de
ROI usando el mock, que el motor de plantilla sí lee. Están deliberadamente
separados de la lectura del frame real (test_simcore.py): una cosa es que la
lógica sea correcta y otra que el motor sepa leer una tipografía real. Deben
fallar por separado.
"""

import copy

import pytest

from ocr import digitos
from ocr.lector import _extraer_parte, leer_imagen
from ocr.mock import mock_combinado
from ocr.motor.base import LectorOCR
from ocr.perfiles import perfil_desde_dict


class MotorEspia(LectorOCR):
    """Envuelve un motor real y cuenta cuántas veces se le pidió leer."""

    def __init__(self, interno):
        self.interno = interno
        self.llamadas = 0

    def leer(self, imagen):
        self.llamadas += 1
        return self.interno.leer(imagen)


@pytest.fixture(scope="module")
def perfil_combinado():
    return perfil_desde_dict(mock_combinado.derivar_perfil())


def test_pni_combinada_se_parte_en_sis_y_dia(perfil_combinado, motor):
    imagen = mock_combinado.generar_imagen()
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]

    assert signos["pni"] is not None
    assert signos["pni"]["sis"] == 120
    assert signos["pni"]["dia"] == 75
    assert signos["pni"]["media"] == 90
    assert signos["pni"]["unidad"] == "mmHg"


def test_sis_y_dia_no_se_confunden(perfil_combinado, motor):
    """Valores asimétricos: detecta que las partes no estén invertidas."""
    imagen = mock_combinado.generar_imagen({"pni": "144/62"})
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"]["sis"] == 144
    assert signos["pni"]["dia"] == 62


def test_resto_de_signos_sigue_leyendose(perfil_combinado, motor):
    imagen = mock_combinado.generar_imagen()
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["fc"]["valor"] == 142
    assert signos["spo2"]["valor"] == 97
    assert signos["fr"]["valor"] == 48
    assert signos["temp"]["valor"] == 36.9


def test_signo_ausente_es_null(perfil_combinado, motor):
    imagen = mock_combinado.generar_imagen()
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["fp"] == {"valor": None, "unidad": "lpm", "confianza": 0.0}


def test_signo_ausente_no_invoca_el_ocr(perfil_combinado, motor):
    """El perfil tiene 7 signos presentes pero solo 6 ROIs distintas.

    Comprueba dos cosas a la vez: que `fp` (ausente) no gasta una lectura, y que
    el ROI compartido por sis/dia se lee UNA sola vez (así ambos componentes de
    la presión salen de la misma lectura, no de dos pasadas independientes).
    """
    espia = MotorEspia(motor)
    imagen = mock_combinado.generar_imagen()
    leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=espia)
    assert espia.llamadas == 6


def test_pni_media_ilegible_anula_la_presion_entera(perfil_combinado, motor):
    """Regla de seguridad: nunca una presión parcial."""
    imagen = mock_combinado.generar_imagen({"pni_media": None})
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None
    assert signos["fc"]["valor"] == 142


def test_campo_combinado_ilegible_anula_la_presion_entera(perfil_combinado, motor):
    imagen = mock_combinado.generar_imagen({"pni": None})
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None


def test_componente_fuera_de_rango_anula_la_presion_entera(perfil_combinado, motor):
    # 999 es dibujable pero implausible como diastólica
    imagen = mock_combinado.generar_imagen({"pni": "120/999"})
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None


@pytest.mark.parametrize("texto, esperado", [
    ("120/75", ("120", "75")),
    ("98/60", ("98", "60")),
])
def test_extraer_parte_separa_bien(texto, esperado):
    assert _extraer_parte(texto, "/", 0) == esperado[0]
    assert _extraer_parte(texto, "/", 1) == esperado[1]


@pytest.mark.parametrize("texto, media, caso", [
    ("40/75", 90, "diastólica y media por encima de la sistólica"),
    ("75/120", 90, "componentes invertidos"),
    ("120/75", 20, "media por debajo de la diastólica"),
    ("120/75", 150, "media por encima de la sistólica"),
])
def test_pni_incoherente_se_anula_entera(perfil_combinado, motor, texto, media, caso):
    """Ni parcial ni imposible.

    Cada componente se valida contra su propio rango y esos rangos se solapan,
    así que un dígito mal leído da un trío donde cada número es plausible por
    separado pero el conjunto no puede existir. Se descarta como si faltara uno.
    """
    imagen = mock_combinado.generar_imagen({"pni": texto, "pni_media": media})
    signos = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None, f"publicó una presión imposible: {caso}"


def test_pni_neonatal_tipica_sigue_siendo_valida(perfil_combinado, motor):
    """La regla de coherencia no debe descartar lecturas legítimas.

    65/40 con media 48 es la presión neonatal de referencia del contrato, con
    la media calculada como dia + (sis - dia)/3, igual que en el simulador.
    """
    imagen = mock_combinado.generar_imagen({"pni": "65/40", "pni_media": 48})
    pni = leer_imagen(imagen, perfil_combinado, "cama-01", "jetson-01", motor=motor)["signos"]["pni"]
    assert pni is not None
    assert (pni["sis"], pni["dia"], pni["media"]) == (65, 40, 48)


def test_numero_cortado_por_el_borde_no_se_publica(perfil_combinado, motor):
    """Un valor que ya no cabe en su caja se descarta en vez de truncarse.

    Es el fallo más peligroso de una ROI fija: si el monitor pasa a 120/100, la
    caja calibrada para 120/75 corta el último dígito y "120/10" sigue pareciendo
    una presión válida — publicaría shock en un paciente hipertenso.
    """
    datos = copy.deepcopy(mock_combinado.derivar_perfil())
    cfg = mock_combinado.LAYOUT["pni"]
    borde_tinta = cfg["pos"][0] + digitos.ancho_numero("120/75", cfg["alto"])
    x, y, _, h = datos["signos"]["pni_sis"]["roi"]
    estrecha = [x, y, (borde_tinta - 20) - x, h]
    datos["signos"]["pni_sis"]["roi"] = estrecha
    datos["signos"]["pni_dia"]["roi"] = estrecha

    perfil = perfil_desde_dict(datos)
    imagen = mock_combinado.generar_imagen({"pni": "120/75"})
    signos = leer_imagen(imagen, perfil, "cama-01", "jetson-01", motor=motor)["signos"]
    assert signos["pni"] is None


@pytest.mark.parametrize("texto", [None, "", "12075", "120/75/90", "120//75"])
def test_extraer_parte_rechaza_texto_ambiguo(texto):
    """Sin exactamente dos componentes no hay presión: nunca se improvisa una.

    "12075" es el caso peligroso: si el motor no reconoce la barra, leerlo como
    un número entero sería inventar una presión que nadie mostró.
    """
    assert _extraer_parte(texto, "/", 0) is None
    assert _extraer_parte(texto, "/", 1) is None
