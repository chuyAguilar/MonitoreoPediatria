"""Dibujo de dígitos estilo 7 segmentos (blanco sobre negro).

Fuente única de la forma de los dígitos: la usan el generador de la imagen
mock (ocr/mock/generar_mock.py) para dibujar los números y el motor de
plantilla (ocr/motor/plantilla.py) para construir su atlas de comparación.
Compartir el render hace el pipeline determinista de extremo a extremo; es
andamiaje de la iteración 1, no una prueba de robustez ante monitores reales
(ver DECISIONS.md ADR-013).
"""

import numpy as np

# Segmentos encendidos por dígito (nomenclatura estándar a-g):
#   a = superior, b = superior-derecha, c = inferior-derecha, d = inferior,
#   e = inferior-izquierda, f = superior-izquierda, g = centro.
SEGMENTOS_POR_DIGITO = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}


def ancho_digito(alto: int) -> int:
    return max(4, round(alto * 0.55))


def grosor_segmento(alto: int) -> int:
    return max(2, round(alto * 0.14))


def separacion(alto: int) -> int:
    """Espacio horizontal entre glifos de un mismo número."""
    return max(3, round(alto * 0.18))


def dibujar_digito(caracter: str, alto: int) -> np.ndarray:
    """Devuelve el dígito como arreglo uint8 (alto x ancho), 255 sobre 0.

    Los rectángulos de los segmentos comparten esquinas, de modo que cada
    dígito queda como un solo componente conexo (importa para segmentarlos).
    """
    if caracter not in SEGMENTOS_POR_DIGITO:
        raise ValueError(f"Carácter no dibujable como dígito: {caracter!r}")
    ancho = ancho_digito(alto)
    grosor = grosor_segmento(alto)
    mitad = alto // 2
    lienzo = np.zeros((alto, ancho), dtype=np.uint8)
    # Zonas (y0, y1, x0, x1) de cada segmento
    zonas = {
        "a": (0, grosor, 0, ancho),
        "g": (mitad - grosor // 2, mitad - grosor // 2 + grosor, 0, ancho),
        "d": (alto - grosor, alto, 0, ancho),
        "f": (0, mitad, 0, grosor),
        "b": (0, mitad, ancho - grosor, ancho),
        "e": (mitad, alto, 0, grosor),
        "c": (mitad, alto, ancho - grosor, ancho),
    }
    for segmento in SEGMENTOS_POR_DIGITO[caracter]:
        y0, y1, x0, x1 = zonas[segmento]
        lienzo[y0:y1, x0:x1] = 255
    return lienzo


def dibujar_punto(alto: int) -> np.ndarray:
    """Punto decimal: cuadrado pequeño apoyado en la línea de base."""
    grosor = grosor_segmento(alto)
    lienzo = np.zeros((alto, grosor), dtype=np.uint8)
    lienzo[alto - grosor:alto, :] = 255
    return lienzo


def dibujar_numero(texto: str, alto: int) -> np.ndarray:
    """Renderiza una cadena de '0'-'9' y '.' en un renglón, 255 sobre 0."""
    if not texto:
        raise ValueError("Texto vacío")
    glifos = [
        dibujar_punto(alto) if c == "." else dibujar_digito(c, alto) for c in texto
    ]
    sep = separacion(alto)
    ancho_total = sum(g.shape[1] for g in glifos) + sep * (len(glifos) - 1)
    lienzo = np.zeros((alto, ancho_total), dtype=np.uint8)
    x = 0
    for glifo in glifos:
        lienzo[:, x:x + glifo.shape[1]] = glifo
        x += glifo.shape[1] + sep
    return lienzo


def ancho_numero(texto: str, alto: int) -> int:
    """Ancho en píxeles que ocuparía dibujar_numero(texto, alto)."""
    if not texto:
        return 0
    anchos = [
        grosor_segmento(alto) if c == "." else ancho_digito(alto) for c in texto
    ]
    return sum(anchos) + separacion(alto) * (len(texto) - 1)
