"""Transmisión de video de una webcam al servidor (MediaMTX) por RTSP.

Usa ffmpeg para leer /dev/videoN (V4L2), codificar H.264 de baja latencia y
publicar en rtsp://<servidor>:8554/<cama_id>. El mismo cama_id se usa para los
datos (ver contrato), así la web une video + signos vitales.
"""

import subprocess


def iniciar_video_webcam(
    dispositivo,
    cama_id,
    servidor,
    ancho=640,
    alto=480,
    fps=30,
    bitrate="2M",
    formato_entrada="mjpeg",
):
    """Lanza ffmpeg transmitiendo la webcam y devuelve el proceso.

    formato_entrada: formato de captura de la webcam. Por defecto 'mjpeg'
    (cuadros comprimidos, mucho mas ligeros sobre USB) para evitar los
    errores 'v4l2 buffer contains corrupted data' que ocurren al capturar
    en crudo (YUYV) a 640x480/30. Usa 'none' para no forzar formato.
    """
    url = f"rtsp://{servidor}:8554/{cama_id}"
    cmd = ["ffmpeg", "-loglevel", "warning", "-f", "v4l2"]
    if formato_entrada and formato_entrada.lower() != "none":
        cmd += ["-input_format", formato_entrada]
    cmd += [
        "-framerate", str(fps),
        "-video_size", f"{ancho}x{alto}",
        "-i", dispositivo,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-b:v", bitrate,
        "-g", str(fps),
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        url,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
