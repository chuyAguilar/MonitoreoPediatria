"""Motor OCR por plantilla de dígitos 7 segmentos.

Andamiaje de la iteración 1: valida el pipeline completo contra la imagen
mock sin dependencias nuevas. Compara cada glifo de la ROI contra un atlas
dibujado por ocr/digitos.py; la confianza es el índice de Jaccard (área de
tinta coincidente / área de tinta total) mínimo entre los glifos del número —
un score real y explicable, no un valor fijo (ADR-003).

El motor de producción se decidirá con la muestra real del monitor (candidato
principal: PaddleOCR sobre la GPU de la Jetson) y se enchufa vía la interfaz
LectorOCR sin tocar el resto del módulo. Ver DECISIONS.md ADR-013.
"""

import cv2
import numpy as np

from ocr import digitos
from ocr.motor.base import LectorOCR

# Alto al que se dibuja el atlas de plantillas
_ALTO_ATLAS = 64

# Un glifo más bajo que esta fracción del glifo más alto se toma como punto decimal
_FRACCION_ALTO_PUNTO = 0.45

# Componentes con menos tinta que esto se descartan como motas de ruido
_MIN_PIXELES_GLIFO = 12


class LectorPlantilla(LectorOCR):
    """Lee números 7-segmentos comparando glifos contra un atlas de dígitos."""

    def __init__(self):
        self._atlas = {
            caracter: _recorte_ajustado(digitos.dibujar_digito(caracter, _ALTO_ATLAS))
            for caracter in digitos.SEGMENTOS_POR_DIGITO
        }

    def leer(self, imagen: np.ndarray) -> tuple:
        if imagen is None or imagen.size == 0:
            return None, 0.0
        glifos = _separar_glifos(imagen)
        if not glifos:
            return None, 0.0

        alto_maximo = max(g.shape[0] for g in glifos)
        caracteres = []
        confianzas = []
        for glifo in glifos:
            if glifo.shape[0] < alto_maximo * _FRACCION_ALTO_PUNTO:
                caracteres.append(".")
                continue
            caracter, puntaje = self._mejor_digito(glifo)
            caracteres.append(caracter)
            confianzas.append(puntaje)

        if not confianzas:
            # Solo se detectaron puntos/manchas bajas: nada legible
            return None, 0.0
        return "".join(caracteres), float(min(confianzas))

    def _mejor_digito(self, glifo: np.ndarray) -> tuple:
        mejor_caracter = None
        mejor_puntaje = -1.0
        for caracter, plantilla in self._atlas.items():
            ajustado = cv2.resize(
                glifo,
                (plantilla.shape[1], plantilla.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
            puntaje = _jaccard(ajustado, plantilla)
            if puntaje > mejor_puntaje:
                mejor_puntaje = puntaje
                mejor_caracter = caracter
        return mejor_caracter, max(0.0, min(1.0, mejor_puntaje))


def _separar_glifos(binaria: np.ndarray) -> list:
    """Divide la ROI binaria en glifos por proyección vertical (columnas vacías).

    Devuelve cada glifo recortado a su caja ajustada, en orden izquierda→derecha.
    """
    columnas_con_tinta = binaria.any(axis=0)
    glifos = []
    inicio = None
    for x, tiene in enumerate(list(columnas_con_tinta) + [False]):
        if tiene and inicio is None:
            inicio = x
        elif not tiene and inicio is not None:
            tira = binaria[:, inicio:x]
            inicio = None
            if int(np.count_nonzero(tira)) < _MIN_PIXELES_GLIFO:
                continue
            filas = np.where(tira.any(axis=1))[0]
            glifos.append(tira[filas[0]:filas[-1] + 1, :])
    return glifos


def _recorte_ajustado(imagen: np.ndarray) -> np.ndarray:
    """Recorta la imagen a la caja mínima que contiene tinta."""
    filas = np.where(imagen.any(axis=1))[0]
    columnas = np.where(imagen.any(axis=0))[0]
    return imagen[filas[0]:filas[-1] + 1, columnas[0]:columnas[-1] + 1]


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    """Índice de Jaccard entre las máscaras de tinta de dos imágenes binarias."""
    tinta_a = a > 127
    tinta_b = b > 127
    union = int(np.count_nonzero(tinta_a | tinta_b))
    if union == 0:
        return 0.0
    interseccion = int(np.count_nonzero(tinta_a & tinta_b))
    return interseccion / union
