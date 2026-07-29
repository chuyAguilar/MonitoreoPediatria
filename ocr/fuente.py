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
