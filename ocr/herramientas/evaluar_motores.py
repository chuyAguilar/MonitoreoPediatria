"""Evaluación reproducible de motores OCR sobre el frame real de SimCore.

Es el experimento que respalda ADR-016. Mide, por motor disponible:

- lectura por signo sobre el frame limpio (texto y confianza),
- robustez: qué emite el pipeline completo sobre frames transformados
  (blur, brillo, contraste, ruido, reescala) y cuántos valores FALSOS emite,
- comportamiento en el fallo: casos donde lo correcto es NO leer.

Motores que no estén instalados se saltan (no es un error). Los motores
integrados se prueban a través de sus módulos reales (ocr.motor.rapid = el de
producción, ADR-017; ocr.motor.paddle = alternativo/histórico); EasyOCR y
Tesseract llevan un adaptador local aquí porque no están integrados.

Uso:
    pip install -r ocr/requirements-motor.txt    # RapidOCR (producción)
    pip install paddleocr easyocr pytesseract    # para comparar
    python -m ocr.herramientas.evaluar_motores
"""

import time
from pathlib import Path

import cv2
import numpy as np

import ocr
from ocr import preproceso
from ocr.lector import leer_imagen
from ocr.motor.base import LectorOCR
from ocr.perfiles import cargar_perfil

DIR = Path(ocr.__file__).parent / "perfiles" / "simcore"
FRAME = cv2.imread(str(DIR / "frame_simcore.png"), cv2.IMREAD_COLOR)
PERFIL = cargar_perfil(DIR / "simcore.json")

REAL = {"fc": 74, "spo2": 98, "fr": 14, "temp": 36.8}
PNI = {"sis": 120, "dia": 75, "media": 90}
BLANCO = "0123456789/."


# --- Adaptadores de los motores NO integrados (solo para comparar) ---------
class AdaptadorEasyOCR(LectorOCR):
    nombre = "easyocr"

    def __init__(self):
        import easyocr
        self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    def leer(self, imagen):
        if imagen is None or imagen.size == 0:
            return None, 0.0
        res = self._reader.readtext(imagen, allowlist=BLANCO, detail=1, paragraph=False)
        if not res:
            return None, 0.0
        res.sort(key=lambda r: r[0][0][0])
        texto = "".join(r[1] for r in res)
        return (texto or None), min(float(r[2]) for r in res)


class AdaptadorTesseract(LectorOCR):
    nombre = "tesseract"

    def __init__(self):
        import pytesseract
        self._pt = pytesseract
        self._pt.get_tesseract_version()  # falla si no hay binario

    def leer(self, imagen):
        from pytesseract import Output
        cfg = "--psm 7 -c tessedit_char_whitelist=" + BLANCO
        data = self._pt.image_to_data(imagen, config=cfg, output_type=Output.DICT)
        piezas = [(t, float(c) / 100.0) for t, c in zip(data["text"], data["conf"])
                  if t.strip() and float(c) >= 0]
        if not piezas:
            return None, 0.0
        return "".join(t for t, _ in piezas), min(c for _, c in piezas)


def motores_disponibles():
    motores = []
    try:
        from ocr.motor.rapid import LectorRapidOCR
        m = LectorRapidOCR()
        m.nombre = "rapidocr"  # motor de PRODUCCIÓN (ADR-017)
        motores.append(m)
    except Exception as e:
        print(f"[no disponible] rapidocr: {type(e).__name__}")
    try:
        from ocr.motor.paddle import LectorPaddleOCR
        m = LectorPaddleOCR()
        m.nombre = "paddleocr"  # alternativo/histórico (ADR-016; segfaultea en aarch64)
        motores.append(m)
    except Exception as e:
        print(f"[no disponible] paddleocr: {type(e).__name__}")
    for Ad in (AdaptadorEasyOCR, AdaptadorTesseract):
        try:
            motores.append(Ad())
        except Exception as e:
            print(f"[no disponible] {Ad.nombre}: {type(e).__name__}")
    return motores


def _rois_distintas():
    vistas = {}
    for nombre, cfg in PERFIL.signos.items():
        if cfg.presente and cfg.roi not in vistas:
            clave = "pni" if cfg.separador is not None else nombre
            vistas[cfg.roi] = clave
    return vistas


def _transformaciones():
    rng = np.random.RandomState(42)
    yield "original", FRAME
    yield "blur1", cv2.GaussianBlur(FRAME, (0, 0), 1.0)
    yield "blur2", cv2.GaussianBlur(FRAME, (0, 0), 2.0)
    yield "brillo-40", np.clip(FRAME.astype(int) - 40, 0, 255).astype(np.uint8)
    yield "brillo+40", np.clip(FRAME.astype(int) + 40, 0, 255).astype(np.uint8)
    yield "contraste0.7", np.clip(FRAME.astype(float) * 0.7, 0, 255).astype(np.uint8)
    yield "ruido", np.clip(FRAME.astype(int) + rng.normal(0, 12, FRAME.shape).astype(int), 0, 255).astype(np.uint8)
    for esc in (0.85, 1.15):
        r = cv2.resize(FRAME, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
        yield f"reescala{esc}", cv2.resize(r, (FRAME.shape[1], FRAME.shape[0]), interpolation=cv2.INTER_AREA)


def _valores_falsos(msg):
    s = msg["signos"]
    falsos = [f"{k}={s[k]['valor']}" for k, v in REAL.items()
              if s[k]["valor"] is not None and s[k]["valor"] != v]
    if s["pni"] is not None and any(s["pni"][k] != v for k, v in PNI.items()):
        falsos.append("pni_incoherente")
    return falsos


def _correcto(msg):
    s = msg["signos"]
    return (all(s[k]["valor"] == v for k, v in REAL.items())
            and s["fp"]["valor"] is None
            and s["pni"] is not None
            and all(s["pni"][k] == v for k, v in PNI.items()))


def evaluar(motor):
    print(f"\n{'='*64}\nMOTOR: {motor.nombre}\n{'='*64}")

    print("-- lectura por signo (frame limpio) --")
    t0 = time.perf_counter()
    for roi, clave in _rois_distintas().items():
        crop = preproceso.recortar_roi(FRAME, roi).copy()
        texto, conf = motor.leer(crop)
        print(f"   {clave:<10} leido={str(texto):<10} conf={conf:.3f}")
    print(f"   ({(time.perf_counter()-t0)*1000:.0f} ms)")

    print("-- robustez (pipeline completo sobre frames transformados) --")
    correctos = falsos = 0
    for nombre, img in _transformaciones():
        msg = leer_imagen(img, PERFIL, "cama-01", "jetson-01", motor=motor)
        ok = _correcto(msg)
        f = _valores_falsos(msg)
        correctos += ok
        falsos += len(f)
        print(f"   {nombre:<14} {'OK' if ok else ('FALSO ' + ','.join(f) if f else 'parcial (algun null)')}")
    print(f"   -> {correctos}/9 completos, {falsos} valores FALSOS emitidos")


def main():
    motores = motores_disponibles()
    if not motores:
        print("Ningún motor disponible. Instala al menos uno (ver el encabezado).")
        return 1
    for m in motores:
        evaluar(m)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
