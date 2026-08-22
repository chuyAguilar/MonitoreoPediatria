"""Disciplina del CLI: wiring positivo, cortes tempranos y errores accionables."""

import shutil

import pytest

from ocr import dispositivos
from video import transmisor, transmitir

from .conftest import JIELI, ULTRASEMI


class _SupervisorStub:
    """Captura los kwargs del wiring; no lanza nada."""

    instancias = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.corridas = 0
        self.una_vez_llamado = 0
        _SupervisorStub.instancias.append(self)

    def correr(self):
        self.corridas += 1

    def una_vez(self):
        self.una_vez_llamado += 1
        return 3


@pytest.fixture(autouse=True)
def _limpiar_stub():
    _SupervisorStub.instancias = []
    yield
    _SupervisorStub.instancias = []


@pytest.fixture()
def con_ffmpeg(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda nombre: "/usr/bin/ffmpeg")


def test_wiring_positivo(monkeypatch, con_ffmpeg):
    # El CLI debe entregar al supervisor EXACTAMENTE lo parseado.
    monkeypatch.setattr(transmisor, "SupervisorTransmision", _SupervisorStub)
    codigo = transmitir.main([
        "--cama-id", "cama-09", "--dispositivo", "usb-0:2.2",
        "--servidor", "10.0.0.5", "--puerto-rtsp", "9554",
        "--resolucion", "640x480", "--fps", "15", "--bitrate", "800k",
        "--formato-entrada", "none", "--timeout-progreso", "7",
    ])
    assert codigo == 0
    (stub,) = _SupervisorStub.instancias
    assert stub.corridas == 1 and stub.una_vez_llamado == 0
    assert stub.kwargs == dict(
        dispositivo="usb-0:2.2", cama_id="cama-09", servidor="10.0.0.5",
        puerto=9554, ancho=640, alto=480, fps=15, bitrate="800k",
        formato_entrada="none", timeout_progreso=7.0,
    )


def test_una_vez_pasa_el_codigo_de_ffmpeg(monkeypatch, con_ffmpeg):
    monkeypatch.setattr(transmisor, "SupervisorTransmision", _SupervisorStub)
    codigo = transmitir.main([
        "--cama-id", "cama-09", "--dispositivo", "usb-0:2.2", "--una-vez",
    ])
    assert codigo == 3  # passthrough del código de salida de ffmpeg
    (stub,) = _SupervisorStub.instancias
    assert stub.una_vez_llamado == 1 and stub.corridas == 0


def test_listar_dispositivos_corta_antes_de_todo(monkeypatch, capsys):
    # --listar-dispositivos debe funcionar SIN cama-id, SIN ffmpeg y SIN
    # construir el supervisor: es la herramienta para descubrir la identidad.
    monkeypatch.setattr(dispositivos, "listar_dispositivos",
                        lambda: [ULTRASEMI, JIELI])
    def bomba(*a, **k):
        raise AssertionError("no debe llegar aquí")
    monkeypatch.setattr(shutil, "which", bomba)
    monkeypatch.setattr(transmisor, "SupervisorTransmision", bomba)

    codigo = transmitir.main(["--listar-dispositivos"])
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "35562055" in salida
    assert "usb-Jieli_Technology_USB_Composite_Device" in salida
    assert "platform-3610000.usb-usb-0:2.2:1.0" in salida


def test_listar_sin_capturas_devuelve_1(monkeypatch, capsys):
    monkeypatch.setattr(dispositivos, "listar_dispositivos", lambda: [])
    assert transmitir.main(["--listar-dispositivos"]) == 1
    assert "Ningún dispositivo con nodo de captura" in capsys.readouterr().out


def test_cama_id_invalido_error_accionable(capsys):
    with pytest.raises(SystemExit):
        transmitir.main(["--cama-id", "cama9", "--dispositivo", "x5000"])
    assert "cama-NN" in capsys.readouterr().err


def test_cama_id_y_dispositivo_obligatorios(capsys):
    with pytest.raises(SystemExit):
        transmitir.main([])
    assert "obligatorios" in capsys.readouterr().err


def test_resolucion_y_bitrate_malformados(capsys):
    with pytest.raises(SystemExit):
        transmitir.main(["--cama-id", "cama-09", "--dispositivo", "x5000",
                         "--resolucion", "720p"])
    assert "ANCHOxALTO" in capsys.readouterr().err
    for malo in ("2mbps", "0k", "0M"):
        with pytest.raises(SystemExit):
            transmitir.main(["--cama-id", "cama-09", "--dispositivo", "x5000",
                             "--bitrate", malo])
        assert "sufijo" in capsys.readouterr().err


def test_timeout_progreso_invalido_rechazado(capsys):
    # 0/negativo derribaría ffmpeg sanos en bucle; nan/inf DESACTIVAN el
    # watchdog en silencio (toda comparación > nan es False).
    for malo in ("0", "-5", "nan", "inf", "1.5"):
        with pytest.raises(SystemExit):
            transmitir.main(["--cama-id", "cama-09", "--dispositivo", "x5000",
                             "--timeout-progreso", malo])
        assert "timeout-progreso" in capsys.readouterr().err


def test_ffmpeg_ausente_exit_1_accionable(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda nombre: None)
    codigo = transmitir.main(["--cama-id", "cama-09", "--dispositivo", "x5000"])
    assert codigo == 1
    assert "ffmpeg" in capsys.readouterr().out


def test_camara_inexistente_exit_1_con_mensaje(monkeypatch, con_ffmpeg, capsys):
    class _SupervisorQueFalla(_SupervisorStub):
        def correr(self):
            raise RuntimeError(
                "No hay ningún dispositivo de captura que coincida con 'x5000'"
            )
    monkeypatch.setattr(transmisor, "SupervisorTransmision", _SupervisorQueFalla)
    codigo = transmitir.main(["--cama-id", "cama-09", "--dispositivo", "x5000"])
    assert codigo == 1
    salida = capsys.readouterr().out
    # el mensaje debe ser ACCIONABLE (nombra lo pedido), no un ERROR pelado
    assert "ERROR" in salida and "x5000" in salida


def test_fatal_de_corrida_exit_1(monkeypatch, con_ffmpeg, capsys):
    class _SupervisorFatal(_SupervisorStub):
        def correr(self):
            raise transmisor.TransmisionFatal("el nodo ahora es OTRA cámara")
    monkeypatch.setattr(transmisor, "SupervisorTransmision", _SupervisorFatal)
    codigo = transmitir.main(["--cama-id", "cama-09", "--dispositivo", "0"])
    assert codigo == 1
    assert "OTRA cámara" in capsys.readouterr().out
