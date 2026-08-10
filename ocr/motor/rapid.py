"""Motor OCR de producción: RapidOCR sobre ONNX Runtime.

Sustituye a PaddleOCR como motor de producción (ADR-017): en la Jetson Orin
(aarch64) el motor de inferencia de Paddle segfaultea de forma reproducible,
mientras que `onnxruntime` corre estable. RapidOCR ejecuta los mismos modelos
PP-OCR (v4) exportados a ONNX, **empaquetados dentro del wheel** — no descarga
nada en runtime, lo que resuelve el despliegue hospitalario sin internet.

Se usa en **modo reconocimiento** (`use_det=False, use_cls=False`): las ROIs
del perfil ya aíslan cada número, la detección sobra. Forma del retorno
verificada con sonda contra rapidocr-onnxruntime 1.4.4:

    engine(img, use_det=False, use_cls=False, use_rec=True)
      -> ([[texto, score]], [tiempos])       # una entrada por imagen
    imagen vacía -> ([['', 0.0]], ...)       # texto vacío, score 0

La dependencia es **opcional** y se importa de forma perezosa aquí dentro,
nunca al importar `ocr` (ver ocr/requirements-motor.txt y
ocr.lector.motor_por_defecto).
"""

import numpy as np

from ocr.motor.base import LectorOCR


class LectorRapidOCR(LectorOCR):
    """Adaptador de RapidOCR (ONNX Runtime) a la interfaz LectorOCR.

    Recibe el recorte CRUDO de la ROI (BGR o gris; la interfaz entrega crudo
    desde la iteración 3, ADR-016) y devuelve (texto, confianza en [0,1]).
    """

    def __init__(self):
        # Import perezoso: la dependencia solo se carga al instanciar el motor
        # real, nunca al importar ocr ni al correr el andamiaje.
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()

    def leer(self, imagen: np.ndarray) -> tuple:
        if imagen is None or imagen.size == 0:
            return None, 0.0
        # El recorte llega como vista no contigua del frame; la sonda mostró
        # que el engine la acepta, pero el buffer contiguo es un seguro barato.
        imagen = np.ascontiguousarray(imagen)

        salida = self._engine(imagen, use_det=False, use_cls=False, use_rec=True)
        # (resultado, tiempos); defensivo por si alguna variante no envuelve
        resultado = salida[0] if isinstance(salida, tuple) else salida
        if not resultado:
            return None, 0.0

        # Rec-only devuelve UNA entrada [texto, score] por imagen; si alguna
        # versión partiera el campo en varias, se concatena en orden y la
        # confianza es la mínima (criterio conservador, como en el resto del
        # módulo: la peor pieza manda).
        textos = []
        confianzas = []
        for entrada in resultado:
            texto_crudo, score = entrada[0], entrada[1]
            # Saneo mínimo: quitar espacios, nada más. NO se recortan
            # caracteres no numéricos: si el modelo leyó "NIBP" o "1O2",
            # dejar la letra hace que el lector lo rechace entero
            # (_interpretar) en vez de convertirlo en un número inventado.
            texto = "".join((texto_crudo or "").split())
            if not texto:
                continue
            try:
                confianzas.append(float(score))
            except (TypeError, ValueError):
                return None, 0.0
            textos.append(texto)

        if not textos:
            return None, 0.0
        return "".join(textos), min(confianzas)
