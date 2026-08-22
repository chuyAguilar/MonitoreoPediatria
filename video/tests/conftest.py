"""Fixtures del runner de video: procesos y relojes falsos, cámaras enlatadas.

Ningún test lanza ffmpeg ni toca V4L2: el supervisor recibe todas sus costuras
(`lanzar`, `resolver`, `identidad_de`, `dormir`, `reloj`) y los dispositivos
son `DispositivoCaptura` enlatados con los datos REALES de la sonda del banco
(21-ago-2026): la capturadora UltraSemi (serial único) y la webcam Jieli (sin
serial: su by-id no trae serial y el token final "Device" es placeholder).
"""

import subprocess

from ocr.dispositivos import (
    V4L2_CAP_META_CAPTURE,
    V4L2_CAP_VIDEO_CAPTURE,
    DispositivoCaptura,
)

CAP = V4L2_CAP_VIDEO_CAPTURE
META = V4L2_CAP_META_CAPTURE

# Sonda real del banco (21-ago-2026): la capturadora quedó en video0/1 y la
# webcam en video2/3 — al revés que en la sonda de la iteración 7: el baile de
# índices que motiva toda la disciplina de identidad.
ULTRASEMI = DispositivoCaptura(
    nombre="USB3 Video: USB3 Video",
    by_id="usb-UltraSemi_USB3_Video_35562055",
    by_path="platform-3610000.usb-usb-0:1.3:1.0",
    serial="35562055",
    nodos=(("/dev/video0", CAP), ("/dev/video1", META)),
    nodos_captura=("/dev/video0",),
    nodo_captura="/dev/video0",
)

JIELI = DispositivoCaptura(
    nombre="USB Composite Device: USB Camer",
    by_id="usb-Jieli_Technology_USB_Composite_Device",
    by_path="platform-3610000.usb-usb-0:2.2:1.0",
    serial="Device",
    nodos=(("/dev/video2", CAP), ("/dev/video3", META)),
    nodos_captura=("/dev/video2",),
    nodo_captura="/dev/video2",
)

# La misma webcam Jieli enchufada en OTRO puerto: mismo by-id (sin serial no
# distingue unidades), by-path distinto. El caso que el pin por by-path detecta.
JIELI_OTRO_PUERTO = DispositivoCaptura(
    nombre="USB Composite Device: USB Camer",
    by_id="usb-Jieli_Technology_USB_Composite_Device",
    by_path="platform-3610000.usb-usb-0:2.4:1.0",
    serial="Device",
    nodos=(("/dev/video2", CAP), ("/dev/video3", META)),
    nodos_captura=("/dev/video2",),
    nodo_captura="/dev/video2",
)

# La MISMA Jieli (mismo puerto, mismo by-id/by-path) tras re-enumerar en otro
# nodo: el pin debe coincidir y el runner seguirla al nodo nuevo.
JIELI_EN_VIDEO5 = DispositivoCaptura(
    nombre="USB Composite Device: USB Camer",
    by_id="usb-Jieli_Technology_USB_Composite_Device",
    by_path="platform-3610000.usb-usb-0:2.2:1.0",
    serial="Device",
    nodos=(("/dev/video5", CAP), ("/dev/video6", META)),
    nodos_captura=("/dev/video5",),
    nodo_captura="/dev/video5",
)


class RelojFalso:
    """Reloj monotónico manual: los tests avanzan el tiempo, nadie duerme."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avanzar(self, segundos):
        self.t += segundos


class ProcesoFalso:
    """Un "ffmpeg" guionizado.

    - `ticks_vivo`: cuántos wait(timeout=1) sobrevive antes de salir; el reloj
      falso avanza 1 s por tick (como el poll real del supervisor). None =
      vive hasta que lo maten (el caso estancado).
    - `al_tick`: callback por tick — los tests "sanos" lo usan para renovar la
      marca de progreso del supervisor, simulando el hilo lector.
    - `ignora_terminate`: no muere con terminate (fuerza la escalada a kill).
    - `ignora_kill`: tampoco muere con kill (estado D: driver v4l2 colgado).
    - `lanza_en_wait`: excepción a lanzar en el primer wait (Ctrl+C real).
    - `stdout`: iterable de líneas -progress para ejercitar el hilo lector
      real (None = sin pipe, como --una-vez).
    """

    def __init__(self, codigo=1, ticks_vivo=0, reloj=None, al_tick=None,
                 ignora_terminate=False, ignora_kill=False, lanza_en_wait=None,
                 stdout=None):
        self.codigo = codigo
        self.ticks_restantes = ticks_vivo
        self.reloj = reloj
        self.al_tick = al_tick
        self.ignora_terminate = ignora_terminate
        self.ignora_kill = ignora_kill
        self.lanza_en_wait = lanza_en_wait
        self.terminado = False
        self.matado = False
        self._codigo_salida = None
        self.stdout = stdout

    def poll(self):
        return self._codigo_salida

    def terminate(self):
        self.terminado = True
        if not self.ignora_terminate:
            self._codigo_salida = -15

    def kill(self):
        self.matado = True
        if not self.ignora_kill:
            self._codigo_salida = -9

    def wait(self, timeout=None):
        if self.lanza_en_wait is not None:
            exc, self.lanza_en_wait = self.lanza_en_wait, None
            raise exc
        if self._codigo_salida is not None:
            return self._codigo_salida
        if timeout is None and self.ticks_restantes is None:
            # El contrato real de Popen.wait() sin timeout es BLOQUEAR para
            # siempre sobre un proceso que no sale: enmascararlo dejaría
            # pasar deadlocks reales con la suite verde.
            raise AssertionError(
                "deadlock: wait() sin timeout sobre un proceso vivo que no "
                "sale solo"
            )
        if timeout is not None:
            if self.reloj is not None:
                self.reloj.avanzar(timeout)
            if self.al_tick is not None:
                self.al_tick()
            if self.ticks_restantes is None:
                # vive hasta que lo maten (estancado)
                raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
            if self.ticks_restantes > 0:
                self.ticks_restantes -= 1
                raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
        # sin timeout, o se agotaron los ticks: el proceso "sale"
        self._codigo_salida = self.codigo
        return self._codigo_salida
