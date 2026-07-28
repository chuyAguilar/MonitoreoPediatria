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
    """Motor de producción (PaddleOCR). Salta si la dependencia no está instalada.

    Cargar el modelo es lento (~segundos): scope de sesión para pagarlo una vez.
    """
    pytest.importorskip("paddleocr", reason="motor de producción no instalado")
    from ocr.motor.paddle import LectorPaddleOCR
    return LectorPaddleOCR()
