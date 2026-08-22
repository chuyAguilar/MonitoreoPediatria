"""El argv del ffmpeg es EL artefacto validado en el banco: se fija exacto."""

import pytest

from video.transmisor import comando_ffmpeg, mitad_de_bitrate


def _argv(**cambios):
    base = dict(
        nodo="/dev/video2", cama_id="cama-09", servidor="100.110.157.112",
        puerto=8554, ancho=1280, alto=720, fps=25, bitrate="2M",
    )
    base.update(cambios)
    return comando_ffmpeg(**base)


def test_perfil_defecto_720p_2m():
    cmd = _argv()
    assert cmd[0] == "ffmpeg"
    # entrada V4L2 con MJPG forzado (el crudo YUYV corrompe buffers por USB)
    i = cmd.index("-i")
    assert cmd[i + 1] == "/dev/video2"
    assert cmd[cmd.index("-input_format") + 1] == "mjpeg"
    assert cmd.index("-input_format") < i, "las opciones de entrada van antes de -i"
    assert cmd[cmd.index("-video_size") + 1] == "1280x720"
    assert cmd[cmd.index("-framerate") + 1] == "25"
    # x264 de baja latencia validado
    assert cmd[cmd.index("-preset") + 1] == "ultrafast"
    assert cmd[cmd.index("-tune") + 1] == "zerolatency"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    # 1 keyframe/segundo: -g == fps
    assert cmd[cmd.index("-g") + 1] == "25"
    # CBR con la proporción del banco: 2M/2M/1M
    assert cmd[cmd.index("-b:v") + 1] == "2M"
    assert cmd[cmd.index("-maxrate") + 1] == "2M"
    assert cmd[cmd.index("-bufsize") + 1] == "1M"
    # salida RTSP por TCP a la ruta de la cama
    assert cmd[cmd.index("-rtsp_transport") + 1] == "tcp"
    assert cmd[-1] == "rtsp://100.110.157.112:8554/cama-09"


def test_perfil_bajo_640x480_800k():
    cmd = _argv(ancho=640, alto=480, bitrate="800k", fps=15)
    assert cmd[cmd.index("-video_size") + 1] == "640x480"
    assert cmd[cmd.index("-b:v") + 1] == "800k"
    assert cmd[cmd.index("-maxrate") + 1] == "800k"
    assert cmd[cmd.index("-bufsize") + 1] == "400k"
    assert cmd[cmd.index("-g") + 1] == "15"


def test_progreso_solo_en_modo_supervisado():
    # -progress alimenta el watchdog; en --una-vez nadie drenaría el pipe y
    # ffmpeg se bloquearía escribiendo: debe omitirse.
    supervisado = _argv(progreso=True)
    assert supervisado[supervisado.index("-progress") + 1] == "pipe:1"
    solo = _argv(progreso=False)
    assert "-progress" not in solo


def test_formato_entrada_none_lo_omite():
    cmd = _argv(formato_entrada="none")
    assert "-input_format" not in cmd
    cmd = _argv(formato_entrada="yuyv422")
    assert cmd[cmd.index("-input_format") + 1] == "yuyv422"


def test_mitad_de_bitrate():
    assert mitad_de_bitrate("2M") == "1M"
    assert mitad_de_bitrate("800k") == "400k"
    # mitad no entera en M -> cae a k, no se trunca a 1M
    assert mitad_de_bitrate("3M") == "1500k"
    with pytest.raises(ValueError):
        mitad_de_bitrate("2.5M")
    with pytest.raises(ValueError):
        mitad_de_bitrate("2000000")
