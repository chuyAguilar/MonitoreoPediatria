"""Transmite el video RGB de la Femto Bolt al servidor (MediaMTX) por RTSP.

Flujo:
    Femto Bolt --pyorbbecsdk--> este script --raw frames--> ffmpeg (H.264)
        --RTSP--> MediaMTX en el servidor --WebRTC--> navegador

Uso (en la Mac/edge):
    python capture/stream_to_server.py
    python capture/stream_to_server.py --server 100.110.157.112 --path femto \
        --width 1280 --height 720 --fps 30 --bitrate 2M

Requisitos:
    pip install pyorbbecsdk2 opencv-python numpy
    sudo apt install -y ffmpeg
    MediaMTX corriendo en el servidor (ver docs/STREAMING.md)

Detener: Ctrl+C
"""

import argparse
import subprocess
import sys

import cv2

try:
    from pyorbbecsdk import OBError, Pipeline
except ImportError:
    raise SystemExit(
        "No se encontró pyorbbecsdk. Instala con: pip install --upgrade pyorbbecsdk2"
    )

from utils import frame_to_bgr_image


def build_ffmpeg(server: str, path: str, w: int, h: int, fps: int, bitrate: str):
    """Lanza ffmpeg leyendo frames BGR crudos por stdin y publicando RTSP."""
    url = f"rtsp://{server}:8554/{path}"
    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        # Entrada: video crudo desde stdin
        "-f", "rawvideo",
        "-pixel_format", "bgr24",
        "-video_size", f"{w}x{h}",
        "-framerate", str(fps),
        "-i", "-",
        # Codificación H.264 de baja latencia
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-b:v", bitrate,
        "-g", str(fps),  # keyframe cada segundo (WebRTC lo necesita seguido)
        # Salida: RTSP por TCP (más estable sobre Tailscale)
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        url,
    ]
    print(f"Publicando en {url}")
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="100.110.157.112", help="IP del servidor MediaMTX")
    p.add_argument("--path", default="femto", help="nombre del stream")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--bitrate", default="2M")
    args = p.parse_args()

    # 1. Iniciar la cámara (config por defecto: color + profundidad sincronizados)
    try:
        pipeline = Pipeline()
        pipeline.start()
    except OBError as e:
        print(f"ERROR al iniciar la cámara: {e}")
        print("Revisa USB 3.0, alimentación de la cámara y reglas udev.")
        return

    # 2. Iniciar ffmpeg
    ff = build_ffmpeg(
        args.server, args.path, args.width, args.height, args.fps, args.bitrate
    )

    print("Transmitiendo. Ctrl+C para detener.")
    frames_sent = 0
    try:
        while True:
            frames = pipeline.wait_for_frames(1000)
            if frames is None:
                continue
            color_frame = frames.get_color_frame()
            if color_frame is None:
                continue

            image = frame_to_bgr_image(color_frame)
            if image is None:
                continue

            # Redimensionar al tamaño fijo que espera ffmpeg
            if (image.shape[1], image.shape[0]) != (args.width, args.height):
                image = cv2.resize(image, (args.width, args.height))

            try:
                ff.stdin.write(image.tobytes())
            except BrokenPipeError:
                print("ffmpeg se cerró. ¿Está MediaMTX corriendo en el servidor?")
                break

            frames_sent += 1
            if frames_sent % (args.fps * 5) == 0:  # cada ~5 s
                print(f"  {frames_sent} frames enviados")

    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        pipeline.stop()
        if ff.stdin:
            ff.stdin.close()
        ff.wait()
        print(f"Detenido. Frames enviados: {frames_sent}")


if __name__ == "__main__":
    main()
