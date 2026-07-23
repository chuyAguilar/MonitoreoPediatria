"""Genera una imagen mock de monitor de signos vitales + su perfil de ROIs.

La tabla LAYOUT es la única fuente de verdad: de ella salen tanto el dibujo
de la imagen como el perfil de ROIs derivado (derivar_perfil). Así la imagen
y el perfil no pueden desincronizarse.

Uso:
    python -m ocr.mock.generar_mock --salida monitor_mock.png \
        [--perfil-salida ocr/perfiles/monitor_mock.json]

Los tests importan generar_imagen()/derivar_perfil() directamente y no
necesitan archivos en disco.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from ocr import digitos
from ocr.contrato import UNIDADES_CONTRATO

RESOLUCION = (1280, 720)  # (ancho, alto)
MARGEN_ROI = 12           # margen alrededor del número dentro de su ROI
COLOR_FONDO = (12, 12, 12)
COLOR_ETIQUETA = (180, 180, 180)

# Valores por defecto (dentro de los rangos de plausibilidad)
VALORES_DEFECTO = {
    "fc": 142,
    "spo2": 97,
    "fp": 141,
    "fr": 48,
    "temp": 36.9,
    "pni_sis": 66,
    "pni_dia": 39,
    "pni_media": 48,
}

# Por signo: dónde y cómo se dibuja el número. `max_texto` es el texto más
# ancho esperado y dimensiona la ROI. `rango` es de PLAUSIBILIDAD fisiológica
# (amplio, para filtrar basura del OCR), no el "típico neonatal" del contrato.
LAYOUT = {
    "fc":        {"pos": (940, 70),  "alto": 96, "color": (80, 255, 80),   "etiqueta": "FC lpm",   "max_texto": "888",  "tipo": "int",   "rango": (50, 250)},
    "spo2":      {"pos": (940, 240), "alto": 84, "color": (255, 255, 80),  "etiqueta": "SpO2 %",   "max_texto": "888",  "tipo": "int",   "rango": (50, 100)},
    "fp":        {"pos": (940, 390), "alto": 64, "color": (255, 255, 80),  "etiqueta": "FP lpm",   "max_texto": "888",  "tipo": "int",   "rango": (50, 250)},
    "fr":        {"pos": (940, 520), "alto": 64, "color": (80, 255, 255),  "etiqueta": "FR rpm",   "max_texto": "888",  "tipo": "int",   "rango": (10, 120)},
    "temp":      {"pos": (940, 640), "alto": 56, "color": (255, 255, 255), "etiqueta": "Temp C",   "max_texto": "88.8", "tipo": "float", "rango": (30.0, 43.0), "decimales": 1},
    "pni_sis":   {"pos": (80, 600),  "alto": 64, "color": (60, 160, 255),  "etiqueta": "PNI sis",  "max_texto": "888",  "tipo": "int",   "rango": (20, 200)},
    "pni_dia":   {"pos": (330, 600), "alto": 64, "color": (60, 160, 255),  "etiqueta": "PNI dia",  "max_texto": "888",  "tipo": "int",   "rango": (10, 150)},
    "pni_media": {"pos": (580, 600), "alto": 64, "color": (60, 160, 255),  "etiqueta": "PNI media","max_texto": "888",  "tipo": "int",   "rango": (15, 180)},
}


def generar_imagen(valores: dict = None) -> np.ndarray:
    """Dibuja el panel mock. `valores` sobreescribe VALORES_DEFECTO por signo;
    un valor None deja ese signo apagado (ROI vacía), útil para tests."""
    vals = dict(VALORES_DEFECTO)
    if valores:
        vals.update(valores)

    ancho_img, alto_img = RESOLUCION
    lienzo = np.zeros((alto_img, ancho_img, 3), dtype=np.uint8)
    lienzo[:] = COLOR_FONDO
    cv2.putText(lienzo, "MONITOR MOCK", (40, 44),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, COLOR_ETIQUETA, 1, cv2.LINE_AA)

    for nombre, cfg in LAYOUT.items():
        x, y = cfg["pos"]
        cv2.putText(lienzo, cfg["etiqueta"], (x, y - MARGEN_ROI - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_ETIQUETA, 1, cv2.LINE_AA)
        valor = vals[nombre]
        if valor is None:
            continue
        texto = _formatear(valor, cfg)
        if digitos.ancho_numero(texto, cfg["alto"]) > digitos.ancho_numero(cfg["max_texto"], cfg["alto"]):
            raise ValueError(
                f"'{nombre}': el valor {texto!r} es más ancho que max_texto "
                f"{cfg['max_texto']!r}; no cabe en su ROI"
            )
        parche = digitos.dibujar_numero(texto, cfg["alto"])
        mascara = parche > 0
        region = lienzo[y:y + parche.shape[0], x:x + parche.shape[1]]
        region[mascara] = cfg["color"]

    return lienzo


def derivar_perfil() -> dict:
    """Deriva el perfil de ROIs (dict listo para JSON) del mismo LAYOUT."""
    signos = {}
    for nombre, cfg in LAYOUT.items():
        x, y = cfg["pos"]
        ancho_maximo = digitos.ancho_numero(cfg["max_texto"], cfg["alto"])
        signo = {
            "roi": [x - MARGEN_ROI, y - MARGEN_ROI,
                    ancho_maximo + 2 * MARGEN_ROI, cfg["alto"] + 2 * MARGEN_ROI],
            "tipo": cfg["tipo"],
            "unidad": UNIDADES_CONTRATO[nombre],
            "rango": list(cfg["rango"]),
        }
        if "decimales" in cfg:
            signo["decimales"] = cfg["decimales"]
        signos[nombre] = signo
    return {
        "perfil": "monitor-mock-v1",
        "notas": "Derivado automaticamente por ocr/mock/generar_mock.py; no editar a mano.",
        "resolucion": list(RESOLUCION),
        "signos": signos,
    }


def _formatear(valor, cfg) -> str:
    if cfg["tipo"] == "float":
        return f"{valor:.{cfg.get('decimales', 0)}f}"
    return str(int(valor))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ocr.mock.generar_mock",
        description="Genera la imagen mock del monitor y, opcionalmente, su perfil de ROIs",
    )
    parser.add_argument("--salida", default="monitor_mock.png",
                        help="Ruta del PNG a escribir (defecto: monitor_mock.png)")
    parser.add_argument("--perfil-salida",
                        help="Si se indica, escribe ahí el perfil JSON derivado")
    args = parser.parse_args(argv)

    imagen = generar_imagen()
    if not cv2.imwrite(args.salida, imagen):
        raise RuntimeError(f"No se pudo escribir la imagen: {args.salida}")
    print(f"Imagen mock escrita en {args.salida}")

    if args.perfil_salida:
        contenido = json.dumps(derivar_perfil(), ensure_ascii=False, indent=2) + "\n"
        Path(args.perfil_salida).write_text(contenido, encoding="utf-8")
        print(f"Perfil derivado escrito en {args.perfil_salida}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
