import pytest

from ocr.mock import generar_mock
from ocr.motor.plantilla import LectorPlantilla
from ocr.perfiles import perfil_desde_dict


@pytest.fixture(scope="session")
def perfil_mock():
    return perfil_desde_dict(generar_mock.derivar_perfil())


@pytest.fixture(scope="session")
def motor():
    """Andamiaje de plantilla: sin dependencias, para probar el pipeline."""
    return LectorPlantilla()


@pytest.fixture(scope="session")
def motor_produccion():
    """Motor de producción (RapidOCR/onnxruntime, ADR-017). Salta si no está.

    Cargar los modelos tiene coste: scope de sesión para pagarlo una vez.
    """
    pytest.importorskip("rapidocr_onnxruntime", reason="motor de producción no instalado")
    from ocr.motor.rapid import LectorRapidOCR
    return LectorRapidOCR()
