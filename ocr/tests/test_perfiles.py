"""Validación de perfiles de ROI: errores claros ante perfiles mal formados."""

import copy

import pytest

from ocr.mock import generar_mock, mock_combinado
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


# --- Iteración 2: signo ausente y campos combinados -----------------------


@pytest.fixture()
def datos_combinados():
    return copy.deepcopy(mock_combinado.derivar_perfil())


def test_perfil_combinado_es_valido(datos_combinados):
    perfil = perfil_desde_dict(datos_combinados)
    assert perfil.signos["fp"].presente is False
    assert perfil.signos["pni_sis"].parte == 0
    assert perfil.signos["pni_dia"].parte == 1


def test_signo_ausente_no_necesita_roi(datos_validos):
    datos_validos["signos"]["fp"] = {"presente": False}
    perfil = perfil_desde_dict(datos_validos)
    assert perfil.signos["fp"].presente is False
    assert perfil.signos["fp"].roi is None
    assert perfil.signos["fp"].unidad == "lpm"  # la unidad la fija el contrato


def test_signo_ausente_con_roi_es_error(datos_validos):
    datos_validos["signos"]["fp"] = {"presente": False, "roi": [0, 0, 10, 10]}
    with pytest.raises(PerfilInvalido, match="ausente"):
        perfil_desde_dict(datos_validos)


def test_signo_presente_sin_roi_sigue_siendo_error(datos_validos):
    del datos_validos["signos"]["fc"]["roi"]
    with pytest.raises(PerfilInvalido, match="roi"):
        perfil_desde_dict(datos_validos)


def test_presente_no_booleano(datos_validos):
    datos_validos["signos"]["fp"]["presente"] = "no"
    with pytest.raises(PerfilInvalido, match="presente"):
        perfil_desde_dict(datos_validos)


def test_separador_sin_parte(datos_combinados):
    del datos_combinados["signos"]["pni_sis"]["parte"]
    with pytest.raises(PerfilInvalido, match="juntos"):
        perfil_desde_dict(datos_combinados)


def test_separador_de_varios_caracteres(datos_combinados):
    datos_combinados["signos"]["pni_sis"]["separador"] = "//"
    with pytest.raises(PerfilInvalido, match="carácter"):
        perfil_desde_dict(datos_combinados)


def test_separador_que_se_confunde_con_el_numero(datos_combinados):
    datos_combinados["signos"]["pni_sis"]["separador"] = "."
    with pytest.raises(PerfilInvalido, match="separador"):
        perfil_desde_dict(datos_combinados)


def test_parte_fuera_de_rango(datos_combinados):
    datos_combinados["signos"]["pni_sis"]["parte"] = 2
    with pytest.raises(PerfilInvalido, match="parte"):
        perfil_desde_dict(datos_combinados)


def test_sis_y_dia_no_pueden_leer_la_misma_parte(datos_combinados):
    """Error de copiar/pegar que haría que sistólica y diastólica salieran iguales."""
    datos_combinados["signos"]["pni_dia"]["parte"] = 0
    with pytest.raises(PerfilInvalido, match="misma parte"):
        perfil_desde_dict(datos_combinados)


def test_sis_y_dia_no_pueden_ir_invertidas(datos_combinados):
    """La otra mitad del error: partes cambiadas → se publicaría 75/120."""
    datos_combinados["signos"]["pni_sis"]["parte"] = 1
    datos_combinados["signos"]["pni_dia"]["parte"] = 0
    with pytest.raises(PerfilInvalido, match="invertid"):
        perfil_desde_dict(datos_combinados)


# --- ROIs que se pisan ----------------------------------------------------
#
# Dos signos que miran al mismo sitio publican el mismo número como si fueran
# mediciones independientes. Entre fc y fp es especialmente grave: que ambas
# concuerden es el control de calidad de la señal del oxímetro, y una copia
# "concuerda" siempre.


def test_dos_signos_simples_no_pueden_compartir_roi(datos_validos):
    datos_validos["signos"]["pni_media"]["roi"] = list(datos_validos["signos"]["pni_dia"]["roi"])
    with pytest.raises(PerfilInvalido, match="solapan"):
        perfil_desde_dict(datos_validos)


def test_fp_no_puede_copiar_la_roi_de_fc(datos_validos):
    datos_validos["signos"]["fp"]["roi"] = list(datos_validos["signos"]["fc"]["roi"])
    with pytest.raises(PerfilInvalido, match="solapan"):
        perfil_desde_dict(datos_validos)


def test_roi_desplazada_un_pixel_tambien_se_detecta(datos_validos):
    """Leería el mismo número; una comparación exacta no lo vería."""
    roi = list(datos_validos["signos"]["pni_dia"]["roi"])
    roi[0] += 1
    datos_validos["signos"]["pni_media"]["roi"] = roi
    with pytest.raises(PerfilInvalido, match="solapan"):
        perfil_desde_dict(datos_validos)


def test_varios_signos_ausentes_no_dan_falso_positivo(datos_validos):
    """Los ausentes no tienen ROI: no deben contarse como solapados entre sí."""
    datos_validos["signos"]["fp"] = {"presente": False}
    datos_validos["signos"]["temp"] = {"presente": False}
    perfil = perfil_desde_dict(datos_validos)
    assert perfil.signos["fp"].presente is False
    assert perfil.signos["temp"].presente is False
