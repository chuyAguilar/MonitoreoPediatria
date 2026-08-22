"""Clasificación identidad/ruta/índice (réplica de ADR-018) y política de pin.

La frontera de dígitos se fija POR AMBOS LADOS: "0".."999" es índice literal,
un dígito-largo (el serial 35562055) es identidad — interpretarlo como índice
abriría la cámara nº 35562055, un sinsentido silencioso.
"""

import pytest

from ocr.dispositivos import DispositivoCaptura
from video.transmisor import (
    TransmisionFatal,
    clasificar_dispositivo,
    coincide_pin,
    pin_de,
)

from .conftest import JIELI, JIELI_OTRO_PUERTO, ULTRASEMI


def _webcam(by_id, by_path, serial, nodo="/dev/video4"):
    return DispositivoCaptura(
        nombre="Webcam generica", by_id=by_id, by_path=by_path, serial=serial,
        nodos=((nodo, 1),), nodos_captura=(nodo,), nodo_captura=nodo,
    )


def test_indice_literal_a_ruta():
    assert clasificar_dispositivo("0") == ("literal", "/dev/video0")
    assert clasificar_dispositivo("999") == ("literal", "/dev/video999")
    # strip antes de clasificar (lección del unit file de systemd, ADR-018)
    assert clasificar_dispositivo(" 0 ") == ("literal", "/dev/video0")


def test_digito_largo_es_identidad_no_indice():
    assert clasificar_dispositivo("35562055") == ("identidad", "35562055")
    assert clasificar_dispositivo("0035") == ("identidad", "0035")


def test_ruta_literal_tal_cual():
    assert clasificar_dispositivo("/dev/video7") == ("literal", "/dev/video7")
    assert clasificar_dispositivo(
        "/dev/v4l/by-path/platform-x-video-index0"
    ) == ("literal", "/dev/v4l/by-path/platform-x-video-index0")


def test_identidad_pasa_tal_cual():
    assert clasificar_dispositivo("UltraSemi") == ("identidad", "UltraSemi")
    assert clasificar_dispositivo("usb-0:2.2") == ("identidad", "usb-0:2.2")


def test_vacio_es_fatal():
    with pytest.raises(TransmisionFatal):
        clasificar_dispositivo("   ")


# ----------------------------------------------------------------------
# Política de pin (ADR-020, fijada con la sonda real del banco)
# ----------------------------------------------------------------------


def test_pin_con_serial_es_by_id():
    # La capturadora UltraSemi trae serial único: el pin sigue a la UNIDAD
    # aunque cambie de puerto USB.
    assert pin_de(ULTRASEMI) == ("by-id", "usb-UltraSemi_USB3_Video_35562055")


def test_pin_sin_serial_es_by_path():
    # La webcam Jieli no trae serial (token final "Device", sin dígitos =
    # placeholder): el PUERTO es la única ancla física. Dos webcams idénticas
    # intercambiadas compartirían by-id — solo el by-path las distingue.
    assert pin_de(JIELI) == ("by-path", "platform-3610000.usb-usb-0:2.2:1.0")


def test_pin_sin_by_path_cae_a_by_id_y_luego_nombre():
    d = _webcam(by_id="usb-Marca_Modelo", by_path="", serial="Modelo")
    assert pin_de(d) == ("by-id", "usb-Marca_Modelo")
    d2 = DispositivoCaptura(
        nombre="Webcam X", by_id="", by_path="", serial="",
        nodos=(("/dev/video5", 1),), nodos_captura=("/dev/video5",),
        nodo_captura="/dev/video5",
    )
    assert pin_de(d2) == ("nombre", "Webcam X")


def test_pin_serial_placeholder_con_digitos_ancla_al_puerto():
    # iSerial de fábrica idéntico en todas las unidades ("0001", "01.00.00"):
    # trae dígitos pero NO identifica la unidad — el pin debe ser el puerto.
    for placeholder in ("0001", "01.00.00", "20200101"):
        d = _webcam(
            by_id=f"usb-Marca_Cam_{placeholder}",
            by_path="platform-x-usb-0:3.1:1.0",
            serial=placeholder,
        )
        assert pin_de(d) == ("by-path", "platform-x-usb-0:3.1:1.0"), placeholder


def test_pin_by_id_compartido_ancla_al_puerto():
    # Dos unidades enumeradas con el MISMO by-id (serial no único aunque
    # traiga dígitos raros fuera de la lista): anclar al puerto.
    w1 = _webcam(by_id="usb-Marca_Cam_77AA", by_path="platform-x-usb-0:3.1:1.0",
                 serial="77AA", nodo="/dev/video4")
    w2 = _webcam(by_id="usb-Marca_Cam_77AA", by_path="platform-x-usb-0:3.2:1.0",
                 serial="77AA", nodo="/dev/video6")
    assert pin_de(w1, companeros=[w1, w2]) == ("by-path", "platform-x-usb-0:3.1:1.0")
    # sola (sin clon enumerado), el mismo serial raro sí ancla por by-id
    assert pin_de(w1, companeros=[w1, ULTRASEMI]) == ("by-id", "usb-Marca_Cam_77AA")


def test_coincide_pin_compara_el_atributo_fijado():
    pin = pin_de(JIELI)  # ('by-path', ...2.2...)
    assert coincide_pin(pin, JIELI)
    assert not coincide_pin(pin, JIELI_OTRO_PUERTO)
    pin_ultra = pin_de(ULTRASEMI)  # ('by-id', ...35562055)
    assert coincide_pin(pin_ultra, ULTRASEMI)
    assert not coincide_pin(pin_ultra, JIELI)
