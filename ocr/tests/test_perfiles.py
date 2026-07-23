"""Validación de perfiles de ROI: errores claros ante perfiles mal formados."""

import copy

import pytest

from ocr.mock import generar_mock
from ocr.perfiles import PerfilInvalido, perfil_desde_dict


@pytest.fixture()
def datos_validos():
    return copy.deepcopy(generar_mock.derivar_perfil())


def test_perfil_valido_carga(datos_validos):
    perfil = perfil_desde_dict(datos_validos)
    assert perfil.nombre == "monitor-mock-v1"
    assert set(perfil.signos) == {
        "fc", "spo2", "fp", "fr", "temp", "pni_sis", "pni_dia", "pni_media"
    }


def test_falta_un_signo(datos_validos):
    del datos_validos["signos"]["fc"]
    with pytest.raises(PerfilInvalido, match="fc"):
        perfil_desde_dict(datos_validos)


def test_signo_desconocido(datos_validos):
    datos_validos["signos"]["glucosa"] = datos_validos["signos"]["fc"]
    with pytest.raises(PerfilInvalido, match="glucosa"):
        perfil_desde_dict(datos_validos)


def test_roi_fuera_de_la_imagen(datos_validos):
    datos_validos["signos"]["fc"]["roi"] = [1200, 600, 300, 200]
    with pytest.raises(PerfilInvalido, match="fuera de la resoluci"):
        perfil_desde_dict(datos_validos)


def test_roi_con_tamano_no_positivo(datos_validos):
    datos_validos["signos"]["fc"]["roi"] = [10, 10, 0, 50]
    with pytest.raises(PerfilInvalido, match="no positivos"):
        perfil_desde_dict(datos_validos)


def test_unidad_distinta_del_contrato(datos_validos):
    datos_validos["signos"]["temp"]["unidad"] = "F"
    with pytest.raises(PerfilInvalido, match="contrato"):
        perfil_desde_dict(datos_validos)


def test_tipo_invalido(datos_validos):
    datos_validos["signos"]["fc"]["tipo"] = "texto"
    with pytest.raises(PerfilInvalido, match="tipo"):
        perfil_desde_dict(datos_validos)


def test_rango_invertido(datos_validos):
    datos_validos["signos"]["fc"]["rango"] = [250, 50]
    with pytest.raises(PerfilInvalido, match="rango"):
        perfil_desde_dict(datos_validos)


def test_sin_resolucion(datos_validos):
    del datos_validos["resolucion"]
    with pytest.raises(PerfilInvalido, match="resolucion"):
        perfil_desde_dict(datos_validos)
