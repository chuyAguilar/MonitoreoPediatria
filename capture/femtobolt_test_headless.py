"""Prueba de captura de la Femto Bolt SIN pantalla (para uso por SSH).

Captura N frames, reporta resolución/FPS/profundidad por consola y guarda
una imagen de color y una de profundidad en ./capturas para inspección.

Uso:
    python capture/femtobolt_test_headless.py [--frames 60]
"""

import argparse
import os
import time
from datetime import datetime

import cv2
import numpy as np

try:
    from pyorbbecsdk import OBError, Pipeline
except ImportError:
    raise SystemExit(
        "No se encontró pyorbbecsdk. Instala con: pip install --upgrade pyorbbecsdk2"
    )

from utils import depth_frame_to_mm, frame_to_bgr_image

CAPTURAS_DIR = os.path.join(os.path.dirname(__file__), "..", "capturas")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=60, help="frames a capturar")
    args = parser.parse_args()

    try:
        pipeline = Pipeline()
        pipeline.start()
    except OBError as e:
        print(f"ERROR al iniciar la cámara: {e}")
        print("Revisa: USB 3.0, alimentación de la cámara, reglas udev.")
        return

    print(f"Cámara iniciada. Capturando {args.frames} frames...")
    color_ok = depth_ok = 0
    last_color = last_depth_mm = None
    t0 = time.time()

    try:
        for i in range(args.frames):
            frames = pipeline.wait_for_frames(2000)
            if frames is None:
                print(f"  frame {i}: timeout")
                continue

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()

            if color_frame is not None:
                img = frame_to_bgr_image(color_frame)
                if img is not None:
                    color_ok += 1
                    last_color = img
            if depth_frame is not None:
                depth_ok += 1
                last_depth_mm = depth_frame_to_mm(depth_frame)
    finally:
        pipeline.stop()

    elapsed = time.time() - t0
    print("\n--- RESULTADO ---")
    print(f"Frames de color OK:       {color_ok}/{args.frames}")
    print(f"Frames de profundidad OK: {depth_ok}/{args.frames}")
    print(f"Tiempo: {elapsed:.1f}s  (~{color_ok / elapsed:.1f} FPS efectivos)")

    if last_color is not None:
        h, w = last_color.shape[:2]
        print(f"Resolución color: {w}x{h}")
    if last_depth_mm is not None:
        h, w = last_depth_mm.shape[:2]
        valid = last_depth_mm[(last_depth_mm > 20) & (last_depth_mm < 5000)]
        print(f"Resolución profundidad: {w}x{h}")
        if valid.size:
            print(
                f"Profundidad válida: min={valid.min():.0f}mm "
                f"max={valid.max():.0f}mm media={valid.mean():.0f}mm "
                f"({100 * valid.size / last_depth_mm.size:.0f}% píxeles válidos)"
            )

    if last_color is not None and last_depth_mm is not None:
        os.makedirs(CAPTURAS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cv2.imwrite(os.path.join(CAPTURAS_DIR, f"color_{ts}.png"), last_color)
        norm = np.clip(last_depth_mm, 20, 3000)
        norm = ((norm - 20) / (3000 - 20) * 255).astype(np.uint8)
        cv2.imwrite(
            os.path.join(CAPTURAS_DIR, f"depth_vis_{ts}.png"),
            cv2.applyColorMap(norm, cv2.COLORMAP_JET),
        )
        print(f"\nCapturas guardadas en {os.path.abspath(CAPTURAS_DIR)}")
        print("Cópialas a tu máquina para verlas:")
        print("  scp usuario@servidor:~/MonitoreoPediatria/capturas/*.png .")

    if color_ok == 0 and depth_ok == 0:
        print("\nNingún frame recibido — revisa la sección de problemas en docs/INSTALACION_LAPTOP.md")


if __name__ == "__main__":
    main()
