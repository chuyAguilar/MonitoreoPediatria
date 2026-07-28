"""Lectura del frame REAL de SimCore (1920x1080).

- Lo estructural (perfil válido, `fp` ausente, forma del contrato) se comprueba
  con el andamiaje de plantilla, sin depender del motor real.
- La **regla de seguridad** (nunca publicar un valor equivocado) se comprueba
  con AMBOS motores: con plantilla todo sale null, con producción sale el valor
  real; ninguno inventa.
- El **test de aceptación** (leer los dígitos correctos) usa el motor de
  producción: pasa con él instalado, se SALTA sin él (ya no es xfail — el motor
  de producción llegó en la iteración 3, ADR-016).
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
    """Lectura con el andamiaje de plantilla (para los tests estructurales)."""
    return leer_imagen(RUTA_FRAME, perfil_simcore, "cama-01", "jetson-01", motor=motor)


@pytest.fixture(scope="module")
def mensaje_produccion(perfil_simcore, motor_produccion):
    return leer_imagen(RUTA_FRAME, perfil_simcore, "cama-01", "jetson-01", motor=motor_produccion)


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


@pytest.fixture(params=["plantilla", "produccion"])
def mensaje_de_cualquier_motor(request, perfil_simcore, motor):
    """Mensaje del frame leído por cada motor disponible (producción se salta sin él)."""
    if request.param == "plantilla":
        elegido = motor
    else:
        pytest.importorskip("paddleocr", reason="motor de producción no instalado")
        from ocr.motor.paddle import LectorPaddleOCR
        elegido = LectorPaddleOCR()
    return leer_imagen(RUTA_FRAME, perfil_simcore, "cama-01", "jetson-01", motor=elegido)


def test_nunca_publica_un_valor_equivocado(mensaje_de_cualquier_motor):
    """La regla de oro, con CUALQUIER motor.

    Cada signo debe ser o bien `null` (no se pudo leer con garantías) o bien el
    valor que de verdad muestra la pantalla. Lo que no puede pasar nunca es un
    número distinto del real presentado como bueno — ni con el andamiaje (que
    lo deja todo en null) ni con el motor de producción (que lee bien).
    """
    signos = mensaje_de_cualquier_motor["signos"]
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


def test_aceptacion_lee_el_frame_real(mensaje_produccion):
    """El módulo lee correctamente el frame real con el motor de producción.

    Antes era xfail (el andamiaje no leía tipografía real, ADR-014); desde la
    iteración 3 lo lee PaddleOCR (ADR-016). Se salta si el motor no está.
    """
    signos = mensaje_produccion["signos"]
    for clave, esperado in VALORES_REALES.items():
        assert signos[clave]["valor"] == esperado
    assert signos["pni"] is not None
    assert {k: signos["pni"][k] for k in PNI_REAL} == PNI_REAL
    assert signos["fp"]["valor"] is None
