"""Detección de cámaras web conectadas (Linux / V4L2).

Enumera los dispositivos /dev/video* y verifica cuáles entregan imagen real
(los webcams suelen exponer varios nodos, pero solo algunos capturan video).
"""

import glob


def _nombre_v4l2(idx: int) -> str:
    """Lee el nombre legible de la cámara desde /sys, si está disponible."""
    try:
        with open(f"/sys/class/video4linux/video{idx}/name") as f:
            return f.read().strip()
    except OSError:
        return f"video{idx}"


def detectar_camaras(max_idx: int = 10, verificar: bool = True) -> list[tuple[int, str, str]]:
    """Devuelve una lista de (indice, ruta, nombre) de cámaras utilizables.

    Si verificar=True, abre cada dispositivo y confirma que entrega un frame
    (descarta nodos de metadatos que no capturan imagen).
    """
    encontradas = []
    rutas = sorted(glob.glob("/dev/video*"))

    cv2 = None
    if verificar:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError:
            verificar = False  # sin OpenCV, listamos sin verificar

    for ruta in rutas:
        try:
            idx = int(ruta.replace("/dev/video", ""))
        except ValueError:
            continue
        if idx > max_idx:
            continue

        if not verificar:
            encontradas.append((idx, ruta, _nombre_v4l2(idx)))
            continue

        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        abierta = cap.isOpened()
        frame_ok = False
        if abierta:
            frame_ok, _ = cap.read()
        cap.release()
        if abierta and frame_ok:
            encontradas.append((idx, ruta, _nombre_v4l2(idx)))

    return encontradas
