"""Motor OCR de producción: PaddleOCR (reconocimiento de línea).

Elegido en la iteración 3 tras medir PaddleOCR, EasyOCR y Tesseract sobre el
frame real de SimCore (ADR-016): lee los 6 campos con confianza ~1.0, es el más
robusto ante perturbaciones (9/9 frames transformados frente a 6/9 de EasyOCR)
y no alucina dígitos de texto no numérico.

Usa el modelo de **reconocimiento** de PaddleOCR (`TextRecognition`), no la
tubería completa: las ROIs del perfil ya aíslan una línea de texto, así que la
detección sobra y el reconocimiento a secas es más rápido y más preciso.

La dependencia (`paddleocr` + `paddlepaddle`) es **opcional**: se importa de
forma perezosa aquí dentro, nunca al importar `ocr`. Sin ella, el andamiaje y la
suite corren igual (ver ocr/requirements-motor.txt y ocr.lector.motor_por_defecto).
"""

import cv2
import numpy as np

from ocr.motor.base import LectorOCR


class LectorPaddleOCR(LectorOCR):
    """Adaptador de PaddleOCR a la interfaz LectorOCR.

    Recibe el recorte CRUDO de la ROI (la interfaz entrega crudo desde la
    iteración 3, ADR-016) y devuelve (texto, confianza en [0,1]).
    """

    def __init__(self, model_name: str = None):
        # Import perezoso: la dependencia pesada solo se carga al instanciar el
        # motor real, nunca al importar ocr ni al correr el andamiaje.
        from paddleocr import TextRecognition

        self._model = TextRecognition(model_name=model_name) if model_name \
            else TextRecognition()

    def leer(self, imagen: np.ndarray) -> tuple:
        if imagen is None or imagen.size == 0:
            return None, 0.0
        # PaddleOCR espera un arreglo BGR contiguo; el recorte llega como vista
        # no contigua del frame, y puede venir en gris.
        if imagen.ndim == 2:
            imagen = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
        imagen = np.ascontiguousarray(imagen)

        salida = self._model.predict(input=imagen)
        if not salida:
            return None, 0.0
        r = salida[0]
        texto = r.get("rec_text")
        score = r.get("rec_score")

        # Saneo mínimo: quitar espacios, nada más. NO se recortan caracteres no
        # numéricos: si el modelo leyó una letra (p. ej. "1O2" por un cero mal
        # reconocido, o "NIBP" en una ROI equivocada), dejar la letra hace que
        # el lector lo rechace entero (_interpretar) en vez de convertirlo en un
        # número truncado inventado. La regla de oro manda: nunca inventar.
        texto = "".join((texto or "").split())
        if not texto:
            return None, 0.0
        try:
            confianza = float(score)
        except (TypeError, ValueError):
            return None, 0.0
        return texto, confianza
