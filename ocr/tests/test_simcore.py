"""Lectura del frame REAL de SimCore (1920x1080).

Aquí se separa deliberadamente lo que ya funciona de lo que no:

- Lo estructural (perfil válido, `fp` ausente, forma del contrato) y — sobre
  todo — la **regla de seguridad** de no inventar valores se comprueban de
  verdad y pasan hoy.
- La lectura correcta de los dígitos es un `xfail(strict=True)`: el motor de
  plantilla 7-segmentos no reconoce la tipografía sans-serif de un monitor real
  (medición en DECISIONS.md ADR-014). El día que entre un motor capaz, este
  test pasará y `strict` lo convertirá en error, obligando a quitar la marca.
"""

import json
from pathlib import Path

import pytest

import ocr
from ocr.lector import leer_imagen
from ocr.perfiles import cargar_perfil

DIRECTORIO = Path(ocr.__file__).parent / "perfiles" / "simcore"
RUTA_FRAME = DIRECTORIO / "frame_simcore.png"
RUTA_PERFIL = DIRECTORIO / "simcore.json"

# Lo que un humano lee en el frame
VALORES_REALES = {"fc": 74, "spo2": 98, "fr": 14, "temp": 36.8}
PNI_REAL = {"sis": 120, "dia": 75, "media": 90}


@pytest.fixture(scope="module")
def perfil_simcore():
    return cargar_perfil(RUTA_PERFIL)


@pytest.fixture(scope="module")
def mensaje(perfil_simcore, motor):
    return leer_imagen(RUTA_FRAME, perfil_simcore, "cama-01", "jetson-01", motor=motor)


def test_fixtures_estan_en_el_repo():
    assert RUTA_FRAME.exists(), "falta el frame de SimCore"
    assert RUTA_PERFIL.exists(), "falta el perfil de SimCore"


def test_perfil_declara_fp_ausente(perfil_simcore):
    assert perfil_simcore.signos["fp"].presente is False
    assert perfil_simcore.signos["fp"].roi is None


def test_perfil_declara_pni_combinada(perfil_simcore):
    sis = perfil_simcore.signos["pni_sis"]
    dia = perfil_simcore.signos["pni_dia"]
    assert sis.roi == dia.roi, "sis y dia deben leerse del mismo campo combinado"
    assert (sis.separador, sis.parte) == ("/", 0)
    assert (dia.separador, dia.parte) == ("/", 1)


def test_fp_sale_null(mensaje):
    """SimCore no muestra frecuencia de pulso: no se inventa."""
    assert mensaje["signos"]["fp"] == {"valor": None, "unidad": "lpm", "confianza": 0.0}


def test_forma_del_contrato(mensaje):
    assert mensaje["contrato"] == "1.1"
    assert mensaje["origen"] == "ocr"
    assert set(mensaje["signos"]) == {"fc", "spo2", "fp", "fr", "temp", "pni"}
    json.dumps(mensaje)  # debe ser serializable tal cual


def test_nunca_publica_un_valor_equivocado(mensaje):
    """La regla de oro, medida sobre datos reales.

    Cada signo debe ser o bien `null` (no se pudo leer con garantías) o bien el
    valor que de verdad muestra la pantalla. Lo que no puede pasar nunca es un
    número distinto del real presentado como bueno. Este test es el que debe
    seguir en verde pase lo que pase con el motor.
    """
    signos = mensaje["signos"]
    for clave, esperado in VALORES_REALES.items():
        valor = signos[clave]["valor"]
        assert valor is None or valor == esperado, (
            f"{clave}: publicó {valor!r}, la pantalla muestra {esperado!r}"
        )

    pni = signos["pni"]
    if pni is not None:
        assert {k: pni[k] for k in PNI_REAL} == PNI_REAL


def test_valor_nulo_lleva_confianza_cero(mensaje):
    for clave in ("fc", "spo2", "fp", "fr", "temp"):
        if mensaje["signos"][clave]["valor"] is None:
            assert mensaje["signos"][clave]["confianza"] == 0.0


@pytest.mark.xfail(
    strict=True,
    reason="El motor de plantilla 7-seg no lee tipografia sans-serif real "
           "(5/17 digitos, ADR-014). Se resolvera con el motor de produccion; "
           "cuando pase, quitar este xfail.",
)
def test_aceptacion_lee_el_frame_real(mensaje):
    signos = mensaje["signos"]
    for clave, esperado in VALORES_REALES.items():
        assert signos[clave]["valor"] == esperado
    assert signos["pni"] is not None
    assert {k: signos["pni"][k] for k in PNI_REAL} == PNI_REAL
