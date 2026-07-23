"""Preprocesamiento de ROIs antes del OCR.

Convierte el recorte de un signo en una imagen binaria normalizada (dígitos
blancos sobre fondo negro, alto fijo), que es lo que espera la interfaz
LectorOCR (ocr/motor/base.py).
"""

import cv2
import numpy as np

# Alto al que se normaliza toda ROI binarizada
ALTO_NORMALIZADO = 100

# Si el recorte casi no tiene contraste, se considera vacío (evita que Otsu
# convierta ruido de fondo en "tinta")
_CONTRASTE_MINIMO = 40


def recortar_roi(imagen: np.ndarray, roi) -> np.ndarray:
    """Recorta [x, y, w, h] de la imagen (sin copiar)."""
    x, y, w, h = roi
    return imagen[y:y + h, x:x + w]


def binarizar(recorte: np.ndarray) -> np.ndarray:
    """Gris → umbral Otsu → limpieza → alto normalizado.

    El gris se toma como el máximo de los canales: los monitores dibujan cada
    signo en un color distinto (verde, cian, amarillo...) sobre fondo oscuro,
    y el máximo captura cualquier color brillante sin depender de cuál sea.
    """
    if recorte.ndim == 3:
        gris = recorte.max(axis=2)
    else:
        gris = recorte
    gris = np.ascontiguousarray(gris, dtype=np.uint8)

    if int(gris.max()) - int(gris.min()) < _CONTRASTE_MINIMO:
        alto, ancho = _tamano_normalizado(gris.shape)
        return np.zeros((alto, ancho), dtype=np.uint8)

    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Limpieza de motas sueltas (apertura con núcleo pequeño)
    nucleo = np.ones((3, 3), dtype=np.uint8)
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_OPEN, nucleo)

    alto, ancho = _tamano_normalizado(binaria.shape)
    binaria = cv2.resize(binaria, (ancho, alto), interpolation=cv2.INTER_NEAREST)
    return binaria


def _tamano_normalizado(forma) -> tuple:
    """(alto, ancho) tras llevar el alto a ALTO_NORMALIZADO manteniendo aspecto."""
    alto_orig, ancho_orig = forma[:2]
    escala = ALTO_NORMALIZADO / alto_orig
    return ALTO_NORMALIZADO, max(1, round(ancho_orig * escala))
