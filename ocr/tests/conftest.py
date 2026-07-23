import pytest

from ocr.mock import generar_mock
from ocr.motor.plantilla import LectorPlantilla
from ocr.perfiles import perfil_desde_dict


@pytest.fixture(scope="session")
def perfil_mock():
    return perfil_desde_dict(generar_mock.derivar_perfil())


@pytest.fixture(scope="session")
def motor():
    return LectorPlantilla()
