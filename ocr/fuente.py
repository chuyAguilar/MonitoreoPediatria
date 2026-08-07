"""Fuente de frames desacoplada del publicador.

Hoy la fuente es una imagen fija; mañana será la capturadora en vivo (V4L2). El
publicador solo conoce esta interfaz, así que cambiar de una a otra es añadir una
clase, sin tocar el bucle ni el transporte (mismo patrón que la interfaz
LectorOCR del motor).

`cambio()` es la clave del desacople: dice si hay un frame NUEVO desde la última
lectura. El publicador solo re-ejecuta el OCR cuando lo hay. Para una imagen fija
eso significa leer una vez y republicar; para la capturadora en vivo, releer cada
tick (devolverá siempre True).
"""

import time
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np


class FuenteFrames(ABC):
    """Entrega frames BGR listos para `ocr.lector.leer_imagen`."""

    @abstractmethod
    def frame(self) -> np.ndarray:
        """Devuelve el frame actual como arreglo BGR."""
        raise NotImplementedError

    def cambio(self) -> bool:
        """¿Hay un frame nuevo desde la última vez? Por defecto sí (conservador)."""
        return True

    def cerrar(self) -> None:
        """Libera recursos (dispositivo de captura, etc.). No-op por defecto."""


class FuenteImagenFija(FuenteFrames):
    """Una imagen fija leída del disco una sola vez.

    `frame()` devuelve siempre el mismo arreglo; `cambio()` es True solo la
    primera vez (la imagen no cambia), así el publicador OCR-a una vez y luego
    republica la lectura con un `ts` fresco.
    """

    def __init__(self, ruta):
        ruta = str(ruta)
        imagen = cv2.imread(ruta, cv2.IMREAD_COLOR)
        if imagen is None:
            raise ValueError(f"No se pudo leer la imagen de la fuente: {ruta}")
        self._imagen = imagen
        self._ruta = ruta
        self._entregada = False

    def frame(self) -> np.ndarray:
        return self._imagen

    def cambio(self) -> bool:
        if self._entregada:
            return False
        self._entregada = True
        return True

    def __repr__(self):
        alto, ancho = self._imagen.shape[:2]
        nombre = Path(self._ruta).name
        return f"FuenteImagenFija({nombre}, {ancho}x{alto})"


class FuenteCapturadora(FuenteFrames):
    """Captura en vivo de un dispositivo V4L2 (la capturadora HDMI→USB).

    Abre el dispositivo con OpenCV, fija MJPG + la resolución esperada,
    descarta los frames de arranque (salen negros) y valida que el primer
    frame bueno mida exactamente lo que el perfil exige.

    Ante un fallo de lectura reintenta unas pocas veces y luego **lanza**:
    nunca sirve un frame viejo. Republicar un frame congelado con `ts` fresco
    sería presentar datos viejos como actuales — el mismo pecado clínico que
    inventar un número. Al lanzar, el `finally` del bucle publica `offline` y
    la web muestra la cama desconectada, que es la verdad.

    La regla anti-frame-viejo también gobierna el buffering: el backend V4L2
    de OpenCV encola varios frames y `read()` devuelve el MÁS VIEJO, así que a
    1 Hz serviría frames de segundos atrás (y, muerto el dispositivo, seguiría
    sirviendo los encolados como si estuviera vivo). Por eso se fija
    `CAP_PROP_BUFFERSIZE = 1` y cada lectura drena con `grab()` antes del
    `read()` servido: el frame entregado es posterior a la llamada, y la
    muerte del dispositivo se detecta en el mismo tick.
    """

    def __init__(self, dispositivo="/dev/video0", ancho=1920, alto=1080,
                 fourcc="MJPG", frames_de_arranque=15, reintentos_lectura=3):
        if isinstance(dispositivo, str) and dispositivo.isdigit():
            dispositivo = int(dispositivo)  # cv2 acepta índice o ruta /dev/videoN
        self._dispositivo = dispositivo
        self._reintentos = reintentos_lectura
        self._cap = cv2.VideoCapture(dispositivo, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            self.cerrar()
            raise ValueError(
                f"No se pudo abrir la capturadora {dispositivo!r}: ¿existe el "
                f"dispositivo? ¿el usuario tiene permisos de video?"
            )
        try:
            # Cola de 1 frame: read() del backend V4L2 devuelve el más viejo
            # de la cola, y con el buffer por defecto (4) a 1 Hz eso son
            # frames de ~4 s servidos como actuales. Ver docstring.
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # MJPG ANTES que la resolución: es el orden que V4L2 respeta
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            # Los primeros frames tras abrir salen negros (medido en el banco:
            # ~10-15). Se leen y descartan antes del primero útil.
            for _ in range(frames_de_arranque):
                self._cap.read()
            # Validar con un frame real (más fiable que CAP_PROP_*, que algunos
            # drivers reportan bien solo después del primer grab)
            primero = self.frame()
            alto_real, ancho_real = primero.shape[:2]
            if (ancho_real, alto_real) != (ancho, alto):
                raise ValueError(
                    f"La capturadora {dispositivo!r} entrega {ancho_real}x{alto_real} "
                    f"pero se esperaba {ancho}x{alto}: las ROIs del perfil no "
                    f"coincidirían. Revisa el modo del dispositivo (v4l2-ctl)."
                )
        except Exception:
            self.cerrar()
            raise

    def frame(self) -> np.ndarray:
        if self._cap is None:
            raise RuntimeError("La capturadora ya fue cerrada")
        for intento in range(self._reintentos):
            # Drenar el posible frame encolado desde el tick anterior: así el
            # read() servido corresponde a algo capturado DESPUÉS de esta
            # llamada (frescura ≤ ~1 periodo del dispositivo, ~33 ms a 30 fps),
            # y una cola con restos no enmascara la muerte del dispositivo.
            self._cap.grab()
            ok, frame = self._cap.read()
            if ok and frame is not None:
                return frame
            if intento < self._reintentos - 1:
                time.sleep(0.05)  # absorbe el drop ocasional de un frame USB
        raise RuntimeError(
            f"La capturadora {self._dispositivo!r} dejó de entregar frames "
            f"tras {self._reintentos} intentos: ¿se desconectó el dispositivo?"
        )

    # cambio() heredado: True siempre — video en vivo, se re-lee cada tick.

    def cerrar(self) -> None:
        """Libera el dispositivo. Idempotente y a prueba de dobles cierres."""
        cap, self._cap = self._cap, None
        if cap is not None:
            cap.release()

    def __repr__(self):
        return f"FuenteCapturadora({self._dispositivo!r})"
