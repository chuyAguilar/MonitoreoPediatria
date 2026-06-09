"""Transmisión de video de una webcam al servidor (MediaMTX) por RTSP.

Usa ffmpeg para leer /dev/videoN (V4L2), codificar H.264 de baja latencia y
publicar en rtsp://<servidor>:8554/<cama_id>. El mismo cama_id se usa para los
datos (ver contrato), así la web une video + signos vitales.
"""

import subprocess


def iniciar_video_webcam(
    dispositivo: str,
    cama_id: str,
    servidor: str,
    ancho: int = 640,
    alto: int = 480,
    fps: int = 30,
    bitrate: str = "2M",
) -> subprocess.Popen:
    """Lanza ffmpeg transmitiendo la webcam y devuelve el proceso."""
    url = f"rtsp://{servidor}:8554/{cama_id}"
    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        # Entrada: webcam V4L2
        "-f", "v4l2",
        "-framerate", str(fps),
        "-video_size", f"{ancho}x{alto}",
        "-i", dispositivo,
        # Codificación H.264 de baja latencia
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-b:v", bitrate,
        "-g", str(fps),
        # Salida RTSP por TCP
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        url,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
