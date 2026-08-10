"""Interfaz del motor OCR intercambiable.

El resto del módulo (perfiles, preproceso, lector, contrato) solo conoce esta
interfaz. Cambiar de motor es implementar leer() en una clase nueva y pasarla
a ocr.lector.leer_imagen(motor=...) — así entraron PaddleOCR (ADR-016) y
RapidOCR (ADR-017) sin tocar el pipeline. Ver DECISIONS.md ADR-013.
"""

from abc import ABC, abstractmethod

import numpy as np


class LectorOCR(ABC):
    """Motor OCR: recibe una ROI ya preprocesada y devuelve (texto, confianza).

    Contrato de la interfaz:
    - `imagen`: arreglo 2D uint8 binario — dígitos en 255 sobre fondo 0 —
      tal como lo entrega ocr.preproceso.binarizar().
    - Devuelve (texto, confianza):
        * texto: cadena con los caracteres reconocidos ('0'-'9' y '.'),
          o None si no se reconoció nada utilizable.
        * confianza: float en [0, 1]; siempre 0.0 cuando texto es None.
    - No debe lanzar excepciones ante imágenes vacías o ruidosas: ese caso
      es (None, 0.0). La regla de oro es nunca inventar un número.
    """

    @abstractmethod
    def leer(self, imagen: np.ndarray) -> tuple:
        """Devuelve (texto | None, confianza en [0, 1])."""
        raise NotImplementedError
