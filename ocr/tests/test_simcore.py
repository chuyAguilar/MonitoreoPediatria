"""Lectura de los frames REALES de SimCore (1920x1080).

Hay DOS frames de referencia y un solo perfil que debe leer ambos:

- `frame_simcore.png`     — screenshot limpio (iteración 2): protege el pipeline
                            frente a regresiones sobre señal sin artefactos.
- `frame_capturadora.png` — frame real de la cadena de producción (SimCore →
                            HDMI → capturadora → USB → Jetson, iteración 5):
                            lo que el edge ve de verdad. Muestra FC 73 (el
                            screenshot, 74): cada frame tiene sus esperados.

Lo estructural (perfil válido, `fp` ausente, forma del contrato) se comprueba
con el andamiaje de plantilla; la lectura correcta de los dígitos usa el motor
de producción (RapidOCR, ADR-017; se salta si no está instalado). La regla de oro
—nunca publicar un valor equivocado— se comprueba con ambos motores y ambos
frames.
"""

import json
from pathlib import Path

import pytest

import ocr
from ocr.lector import leer_imagen
from ocr.perfiles import cargar_perfil

DIRECTORIO = Path(ocr.__file__).parent / "perfiles" / "simcore"
RUTA_PERFIL = DIRECTORIO / "simcore.json"

# Lo que un humano lee en cada frame (la PNI coincide; la FC no)
PNI_REAL = {"sis": 120, "dia": 75, "media": 90}
FRAMES = {
    "screenshot": (DIRECTORIO / "frame_simcore.png",
                   {"fc": 74, "spo2": 98, "fr": 14, "temp": 36.8}),
    "capturadora": (DIRECTORIO / "frame_capturadora.png",
                    {"fc": 73, "spo2": 98, "fr": 14, "temp": 36.8}),
}


@pytest.fixture(scope="module")
def perfil_simcore():
    return cargar_perfil(RUTA_PERFIL)


@pytest.fixture(scope="module")
def mensaje(perfil_simcore, motor):
    """Lectura del screenshot con el andamiaje (para los tests estructurales)."""
    ruta, _ = FRAMES["screenshot"]
    return leer_imagen(ruta, perfil_simcore, "cama-01", "jetson-01", motor=motor)


def test_fixtures_estan_en_el_repo():
    assert RUTA_PERFIL.exists(), "falta el perfil de SimCore"
    for nombre, (ruta, _) in FRAMES.items():
        assert ruta.exists(), f"falta el frame de referencia '{nombre}'"


def test_perfil_declara_fp_ausente(perfil_simcore):
    assert perfil_simcore.signos["fp"].presente is False
    assert perfil_simcore.signos["fp"].roi is None


def test_perfil_declara_pni_combinada(perfil_simcore):
    sis = perfil_simcore.signos["pni_sis"]
    dia = perfil_simcore.signos["pni_dia"]
    assert sis.roi == dia.roi, "sis y dia deben leerse del mismo campo combinado"
    assert (sis.separador, sis.parte) == ("/", 0)
    assert (dia.separador, dia.parte) == ("/", 1)


def test_pni_no_se_solapa_con_media(perfil_simcore):
    """La caja del campo combinado termina antes de que empiece la de MAP.

    Fija la geometría de la calibración de la capturadora: sis/dia filas
    630..716, pni_media desde 717. Un ensanche descuidado que las solape no
    carga (guarda de ROIs solapadas), pero este test lo dice explícito.
    """
    x, y, w, h = perfil_simcore.signos["pni_sis"].roi
    assert y + h <= perfil_simcore.signos["pni_media"].roi[1]


def test_fp_sale_null(mensaje):
    """SimCore no muestra frecuencia de pulso: no se inventa."""
    assert mensaje["signos"]["fp"] == {"valor": None, "unidad": "lpm", "confianza": 0.0}


def test_forma_del_contrato(mensaje):
    assert mensaje["contrato"] == "1.1"
    assert mensaje["origen"] == "ocr"
    assert set(mensaje["signos"]) == {"fc", "spo2", "fp", "fr", "temp", "pni"}
    json.dumps(mensaje)  # debe ser serializable tal cual


@pytest.fixture(scope="session", params=["plantilla", "produccion"])
def motor_para_regla_de_oro(request, motor):
    if request.param == "plantilla":
        return motor
    pytest.importorskip("rapidocr_onnxruntime", reason="motor de producción no instalado")
    from ocr.motor.rapid import LectorRapidOCR
    return LectorRapidOCR()


@pytest.mark.parametrize("nombre_frame", list(FRAMES))
def test_nunca_publica_un_valor_equivocado(perfil_simcore, motor_para_regla_de_oro, nombre_frame):
    """La regla de oro, con cualquier motor y cualquier frame de referencia.

    Cada signo debe ser o bien `null` (no se pudo leer con garantías) o bien el
    valor que de verdad muestra ESE frame. Nunca un número distinto del real
    presentado como bueno.
    """
    ruta, esperados = FRAMES[nombre_frame]
    signos = leer_imagen(ruta, perfil_simcore, "cama-01", "jetson-01",
                         motor=motor_para_regla_de_oro)["signos"]
    for clave, esperado in esperados.items():
        valor = signos[clave]["valor"]
        assert valor is None or valor == esperado, (
            f"{nombre_frame}/{clave}: publicó {valor!r}, la pantalla muestra {esperado!r}"
        )
    pni = signos["pni"]
    if pni is not None:
        assert {k: pni[k] for k in PNI_REAL} == PNI_REAL


def test_valor_nulo_lleva_confianza_cero(mensaje):
    for clave in ("fc", "spo2", "fp", "fr", "temp"):
        if mensaje["signos"][clave]["valor"] is None:
            assert mensaje["signos"][clave]["confianza"] == 0.0


@pytest.mark.parametrize("nombre_frame", list(FRAMES))
def test_aceptacion_lee_el_frame_real(perfil_simcore, motor_produccion, nombre_frame):
    """El módulo lee correctamente AMBOS frames de referencia con el mismo perfil.

    El perfil está calibrado contra la capturadora (producción) y verificado
    sobre el screenshot: que un solo perfil lea los dos es el invariante que
    protege contra el pequeño desplazamiento entre fuentes. Se salta sin el
    motor de producción.
    """
    ruta, esperados = FRAMES[nombre_frame]
    signos = leer_imagen(ruta, perfil_simcore, "cama-01", "jetson-01",
                         motor=motor_produccion)["signos"]
    for clave, esperado in esperados.items():
        assert signos[clave]["valor"] == esperado
    assert signos["pni"] is not None
    assert {k: signos["pni"][k] for k in PNI_REAL} == PNI_REAL
    assert signos["fp"]["valor"] is None
