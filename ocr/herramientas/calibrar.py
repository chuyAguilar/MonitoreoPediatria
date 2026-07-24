"""Calibrador de ROIs: verifica visualmente un perfil contra un frame.

Es la herramienta con la que se ajusta el perfil de un monitor nuevo. Produce:

- `overlay.png`   — el frame con cada ROI dibujada y etiquetada. Sirve para ver
                    de un vistazo si una caja encuadra el número o si se está
                    comiendo la etiqueta o la unidad de al lado.
- `rois.png`      — tira de contacto: cada ROI ya binarizada por preproceso.py,
                    que es exactamente lo que ve el motor OCR.
- una tabla por consola con el texto leído, la confianza y el valor final.

Con `--detalle` imprime además, por cada glifo, el mejor candidato y el segundo
con sus puntajes. La distancia entre ambos dice si el reconocimiento fue claro
o una moneda al aire (ver DECISIONS.md ADR-013).

Uso:
    python -m ocr.herramientas.calibrar --frame ocr/perfiles/simcore/frame_simcore.png \
        --perfil ocr/perfiles/simcore/simcore.json --salida-dir /tmp/calib --detalle
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from ocr import preproceso
from ocr.lector import _extraer_parte, _interpretar
from ocr.motor.plantilla import LectorPlantilla
from ocr.perfiles import cargar_perfil

_COLOR_CAJA = (0, 0, 255)
_COLOR_TEXTO = (255, 255, 255)
_ANCHO_TIRA = 900


def calibrar(ruta_frame, ruta_perfil, salida_dir=None, motor=None, detalle=False) -> list:
    """Analiza cada ROI del perfil sobre el frame. Devuelve una fila por signo."""
    imagen = cv2.imread(str(ruta_frame), cv2.IMREAD_COLOR)
    if imagen is None:
        raise ValueError(f"No se pudo leer el frame: {ruta_frame}")
    perfil = cargar_perfil(ruta_perfil)
    if motor is None:
        motor = LectorPlantilla()

    alto_img, ancho_img = imagen.shape[:2]
    if (ancho_img, alto_img) != perfil.resolucion:
        raise ValueError(
            f"El frame es {ancho_img}x{alto_img} pero el perfil '{perfil.nombre}' "
            f"describe {perfil.resolucion[0]}x{perfil.resolucion[1]}"
        )

    overlay = imagen.copy()
    filas = []
    recortes = []
    cache = {}

    for nombre, cfg in perfil.signos.items():
        if not cfg.presente:
            filas.append({
                "signo": nombre, "roi": None, "texto": None,
                "confianza": 0.0, "valor": None, "nota": "ausente en el perfil",
                "glifos": [],
            })
            continue

        if cfg.roi not in cache:
            binaria = preproceso.binarizar(preproceso.recortar_roi(imagen, cfg.roi))
            cache[cfg.roi] = (binaria, motor.leer(binaria))
        binaria, (texto, confianza) = cache[cfg.roi]

        texto_parte = texto
        if cfg.separador is not None:
            texto_parte = _extraer_parte(texto, cfg.separador, cfg.parte)
        valor = _interpretar(texto_parte, cfg.tipo)

        glifos = []
        if detalle and hasattr(motor, "diagnosticar"):
            glifos = motor.diagnosticar(binaria)

        filas.append({
            "signo": nombre, "roi": list(cfg.roi), "texto": texto,
            "confianza": round(float(confianza), 3), "valor": valor,
            "nota": "" if cfg.separador is None else f"parte {cfg.parte} de '{texto}'",
            "glifos": glifos,
        })
        recortes.append((nombre, binaria))

        x, y, w, h = cfg.roi
        cv2.rectangle(overlay, (x, y), (x + w, y + h), _COLOR_CAJA, 2)
        cv2.putText(overlay, nombre, (x, max(18, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, _COLOR_TEXTO, 2, cv2.LINE_AA)

    if salida_dir:
        salida = Path(salida_dir)
        salida.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(salida / "overlay.png"), overlay)
        cv2.imwrite(str(salida / "rois.png"), _tira_de_contacto(recortes))

    return filas


def _tira_de_contacto(recortes: list) -> np.ndarray:
    """Apila las ROIs binarizadas, cada una con su nombre, en una sola imagen."""
    if not recortes:
        return np.zeros((40, _ANCHO_TIRA, 3), dtype=np.uint8)
    bloques = []
    for nombre, binaria in recortes:
        color = cv2.cvtColor(binaria, cv2.COLOR_GRAY2BGR)
        if color.shape[1] > _ANCHO_TIRA:
            escala = _ANCHO_TIRA / color.shape[1]
            color = cv2.resize(color, (_ANCHO_TIRA, max(1, round(color.shape[0] * escala))))
        marco = np.zeros((color.shape[0] + 34, _ANCHO_TIRA, 3), dtype=np.uint8)
        marco[34:34 + color.shape[0], :color.shape[1]] = color
        cv2.putText(marco, nombre, (6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 220, 255), 2, cv2.LINE_AA)
        bloques.append(marco)
        bloques.append(np.full((3, _ANCHO_TIRA, 3), 60, dtype=np.uint8))
    return np.vstack(bloques)


def imprimir_tabla(filas: list, detalle: bool = False) -> None:
    print(f"{'signo':<11}{'ROI':<26}{'texto':<12}{'conf':>7}  valor")
    print("-" * 72)
    for fila in filas:
        roi = "" if fila["roi"] is None else str(fila["roi"])
        texto = "-" if fila["texto"] is None else repr(fila["texto"])
        print(f"{fila['signo']:<11}{roi:<26}{texto:<12}{fila['confianza']:>7.3f}  "
              f"{fila['valor']}  {fila['nota']}")

    if not detalle:
        return
    print("\nDetalle por glifo (mejor vs segundo candidato):")
    for fila in filas:
        if not fila["glifos"]:
            continue
        print(f"\n  {fila['signo']}:")
        for i, ranking in enumerate(fila["glifos"]):
            if len(ranking) < 2:
                print(f"    glifo {i}: {ranking[0][0]!r} (punto decimal)")
                continue
            (c1, p1), (c2, p2) = ranking[0], ranking[1]
            print(f"    glifo {i}: {c1!r} {p1:.3f}   2do {c2!r} {p2:.3f}   "
                  f"margen {p1 - p2:+.3f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ocr.herramientas.calibrar",
        description="Verifica y calibra las ROIs de un perfil sobre un frame",
    )
    parser.add_argument("--frame", required=True, help="Ruta a la imagen del monitor")
    parser.add_argument("--perfil", required=True, help="Ruta al perfil JSON")
    parser.add_argument("--salida-dir", help="Directorio donde escribir overlay.png y rois.png")
    parser.add_argument("--detalle", action="store_true",
                        help="Imprime el ranking de candidatos por glifo")
    args = parser.parse_args(argv)

    filas = calibrar(args.frame, args.perfil, args.salida_dir, detalle=args.detalle)
    imprimir_tabla(filas, detalle=args.detalle)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
