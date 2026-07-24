"""Mock de monitor con PNI en campo combinado y un signo ausente.

Reproduce la *estructura* del layout de SimCore (la PNI como "120/75" en un solo
campo, más la media aparte, y sin frecuencia de pulso) pero con los dígitos que
dibuja el propio módulo. Sirve para probar el andamiaje de la iteración 2
—campos combinados, signo ausente, validación de perfil— de forma independiente
de si el motor sabe leer una tipografía real: son dos cosas distintas y conviene
que fallen por separado (ver DECISIONS.md ADR-014).

Como el mock del monitor completo (generar_mock.py), el LAYOUT es la única
fuente de verdad: de él salen la imagen y el perfil.
"""

import cv2
import numpy as np

from ocr import digitos
from ocr.contrato import UNIDADES_CONTRATO

RESOLUCION = (900, 520)
MARGEN_ROI = 10
COLOR_FONDO = (12, 12, 12)
COLOR_ETIQUETA = (170, 170, 170)

VALORES_DEFECTO = {
    "fc": 142,
    "spo2": 97,
    "fr": 48,
    "temp": 36.9,
    "pni": "120/75",
    "pni_media": 90,
}

# Campos dibujables. `clave_valor` indica de qué entrada de VALORES_DEFECTO sale
# el texto; `pni` alimenta un único campo del que se leen sis y dia.
LAYOUT = {
    "fc":        {"pos": (620,  50), "alto": 70, "color": (80, 255, 80),  "etiqueta": "FC",   "max_texto": "888",     "clave_valor": "fc"},
    "spo2":      {"pos": (620, 170), "alto": 70, "color": (255, 255, 80), "etiqueta": "SpO2", "max_texto": "888",     "clave_valor": "spo2"},
    "fr":        {"pos": (620, 290), "alto": 60, "color": (80, 255, 255), "etiqueta": "FR",   "max_texto": "888",     "clave_valor": "fr"},
    "temp":      {"pos": (620, 400), "alto": 56, "color": (255, 255, 255),"etiqueta": "Temp", "max_texto": "88.8",    "clave_valor": "temp"},
    "pni":       {"pos": ( 40, 240), "alto": 76, "color": (60, 160, 255), "etiqueta": "PNI",  "max_texto": "888/888", "clave_valor": "pni"},
    "pni_media": {"pos": ( 40, 400), "alto": 56, "color": (60, 160, 255), "etiqueta": "MAP",  "max_texto": "888",     "clave_valor": "pni_media"},
}

# Rangos de plausibilidad fisiológica (ADR-013), no los típicos del contrato.
RANGOS = {
    "fc": [20, 300],
    "spo2": [50, 100],
    "fr": [3, 120],
    "temp": [25.0, 45.0],
    "pni_sis": [30, 300],
    "pni_dia": [10, 200],
    "pni_media": [15, 250],
}


def generar_imagen(valores: dict = None) -> np.ndarray:
    """Dibuja el panel. Un valor None deja ese campo apagado (ROI vacía)."""
    vals = dict(VALORES_DEFECTO)
    if valores:
        vals.update(valores)

    ancho_img, alto_img = RESOLUCION
    lienzo = np.zeros((alto_img, ancho_img, 3), dtype=np.uint8)
    lienzo[:] = COLOR_FONDO

    for nombre, cfg in LAYOUT.items():
        x, y = cfg["pos"]
        cv2.putText(lienzo, cfg["etiqueta"], (x, y - MARGEN_ROI - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_ETIQUETA, 1, cv2.LINE_AA)
        valor = vals[cfg["clave_valor"]]
        if valor is None:
            continue
        texto = _formatear(valor, nombre)
        if digitos.ancho_numero(texto, cfg["alto"]) > digitos.ancho_numero(cfg["max_texto"], cfg["alto"]):
            raise ValueError(f"'{nombre}': {texto!r} no cabe en su ROI")
        parche = digitos.dibujar_numero(texto, cfg["alto"])
        region = lienzo[y:y + parche.shape[0], x:x + parche.shape[1]]
        region[parche > 0] = cfg["color"]

    return lienzo


def derivar_perfil() -> dict:
    """Perfil con PNI combinada (sis y dia comparten ROI) y `fp` ausente."""
    cajas = {nombre: _caja(cfg) for nombre, cfg in LAYOUT.items()}

    signos = {
        "fc": _signo("fc", cajas["fc"], "int"),
        "spo2": _signo("spo2", cajas["spo2"], "int"),
        "fp": {
            "presente": False,
            "notas": "Este monitor no muestra frecuencia de pulso.",
        },
        "fr": _signo("fr", cajas["fr"], "int"),
        "temp": dict(_signo("temp", cajas["temp"], "float"), decimales=1),
        "pni_sis": dict(_signo("pni_sis", cajas["pni"], "int"), separador="/", parte=0),
        "pni_dia": dict(_signo("pni_dia", cajas["pni"], "int"), separador="/", parte=1),
        "pni_media": _signo("pni_media", cajas["pni_media"], "int"),
    }
    return {
        "perfil": "mock-combinado-v1",
        "notas": "Derivado por ocr/mock/mock_combinado.py; PNI en campo combinado y fp ausente.",
        "resolucion": list(RESOLUCION),
        "signos": signos,
    }


def _caja(cfg) -> list:
    x, y = cfg["pos"]
    ancho = digitos.ancho_numero(cfg["max_texto"], cfg["alto"])
    return [x - MARGEN_ROI, y - MARGEN_ROI,
            ancho + 2 * MARGEN_ROI, cfg["alto"] + 2 * MARGEN_ROI]


def _signo(clave: str, roi: list, tipo: str) -> dict:
    return {
        "roi": list(roi),
        "tipo": tipo,
        "unidad": UNIDADES_CONTRATO[clave],
        "rango": list(RANGOS[clave]),
    }


def _formatear(valor, nombre: str) -> str:
    if isinstance(valor, str):
        return valor
    if nombre == "temp":
        return f"{valor:.1f}"
    return str(int(valor))
