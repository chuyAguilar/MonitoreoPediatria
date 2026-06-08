"""Prueba de captura de la Orbbec Femto Bolt: RGB + profundidad en vivo.

Primer hito del proyecto Monitoreo Pediatría (fases 2-3):
verificar que la cámara entrega ambos streams en la laptop Ubuntu.

Uso:
    python capture/femtobolt_test.py

Controles:
    Q / ESC  — salir
    S        — guardar captura (color PNG + profundidad PNG 16-bit) en ./capturas

Requisitos:
    pip install pyorbbecsdk2 opencv-python numpy
    (ver docs/INSTALACION_LAPTOP.md para reglas udev en Linux)
"""

import os
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

ESC_KEY = 27
MIN_DEPTH_MM = 20      # ignorar lecturas ruidosas muy cercanas
MAX_DEPTH_MM = 3000    # rango útil para una cuna (~0.5-1.5 m de la cámara)
WINDOW_NAME = "Femto Bolt - Color | Profundidad (Q/ESC salir, S guardar)"
CAPTURAS_DIR = os.path.join(os.path.dirname(__file__), "..", "capturas")


def render_depth(depth_mm: np.ndarray) -> np.ndarray:
    """Convierte profundidad en mm a imagen coloreada para visualización."""
    depth_clipped = np.clip(depth_mm, MIN_DEPTH_MM, MAX_DEPTH_MM)
    depth_norm = (depth_clipped - MIN_DEPTH_MM) / (MAX_DEPTH_MM - MIN_DEPTH_MM + 1e-6)
    depth_8bit = (depth_norm * 255).astype(np.uint8)
    return cv2.applyColorMap(depth_8bit, cv2.COLORMAP_JET)


def save_capture(color_image: np.ndarray, depth_mm: np.ndarray) -> None:
    os.makedirs(CAPTURAS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(os.path.join(CAPTURAS_DIR, f"color_{ts}.png"), color_image)
    # Profundidad como PNG de 16 bits (valores en mm)
    cv2.imwrite(
        os.path.join(CAPTURAS_DIR, f"depth_{ts}.png"),
        depth_mm.astype(np.uint16),
    )
    print(f"Captura guardada: {CAPTURAS_DIR}/[color|depth]_{ts}.png")


def main() -> None:
    # Pipeline sin Config: el SDK carga la configuración por defecto
    # (resolución/FPS/formato) y entrega color + profundidad sincronizados.
    try:
        pipeline = Pipeline()
        pipeline.start()
    except OBError as e:
        print(f"Error al iniciar la cámara: {e}")
        print("Verifica: 1) cámara conectada a puerto USB 3.0,")
        print("          2) reglas udev instaladas (ver docs/INSTALACION_LAPTOP.md),")
        print("          3) cable USB original o certificado USB 3.0.")
        return

    print("Cámara iniciada. Q/ESC para salir, S para guardar captura.")
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1280, 480)

    frames_ok = 0
    try:
        while True:
            frames = pipeline.wait_for_frames(1000)  # timeout ms
            if frames is None:
                print("Sin frames (timeout)... reintentando")
                continue

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if color_frame is None or depth_frame is None:
                continue

            color_image = frame_to_bgr_image(color_frame)
            if color_image is None:
                continue
            depth_mm = depth_frame_to_mm(depth_frame)
            depth_image = render_depth(depth_mm)

            frames_ok += 1
            if frames_ok == 1:
                print(
                    f"OK - color: {color_frame.get_width()}x{color_frame.get_height()}, "
                    f"profundidad: {depth_frame.get_width()}x{depth_frame.get_height()}"
                )

            # Mostrar lado a lado a la misma altura
            h = 480
            color_resized = cv2.resize(
                color_image, (int(color_image.shape[1] * h / color_image.shape[0]), h)
            )
            depth_resized = cv2.resize(
                depth_image, (int(depth_image.shape[1] * h / depth_image.shape[0]), h)
            )
            combined = np.hstack((color_resized, depth_resized))
            cv2.imshow(WINDOW_NAME, combined)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), ESC_KEY):
                break
            if key in (ord("s"), ord("S")):
                save_capture(color_image, depth_mm)

    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        pipeline.stop()
        print(f"Cámara detenida. Frames recibidos: {frames_ok}")


if __name__ == "__main__":
    main()
