"""Runner del video de UNA cama: cámara -> x264 baja latencia -> MediaMTX.

Transmitir la webcam de la cama 9 eligiéndola por su puerto físico (la webcam
del banco no tiene serial único; ver --listar-dispositivos y el runbook):
    python -m video.transmitir --cama-id cama-09 --dispositivo usb-0:2.2

Cámara con serial (p. ej. una capturadora): --dispositivo 35562055

Perfil bajo para redes flojas:
    python -m video.transmitir --cama-id cama-09 --dispositivo usb-0:2.2 \
        --resolucion 640x480 --bitrate 800k

Depurar formatos de cámara sin supervisión (un solo lanzamiento):
    python -m video.transmitir --cama-id cama-09 --dispositivo /dev/video2 --una-vez

Detener: Ctrl+C (o SIGTERM: mismo cierre limpio; pensado para systemd futuro).
El runner se relanza solo si el stream cae o se estanca (ADR-020); no publica
MQTT ni toca el OCR: es el runner del VIDEO, como ocr.publicar lo es del dato.
"""

import argparse
import math
import os
import re
import shutil
import signal
import sys

from video import transmisor


def _cama_id(valor):
    """El pegamento del sistema: valida cama-NN (dos dígitos, CONTEXT §6).

    Un typo aquí cuelga el video de una cama EQUIVOCADA en el dashboard — por
    eso el flag es obligatorio, sin default y con formato verificado.
    """
    # re.ASCII: sin él, \d acepta dígitos Unicode (árabes, fullwidth) que
    # producirían una ruta RTSP que la web jamás uniría con los vitales.
    if not re.fullmatch(r"cama-\d{2}", valor, flags=re.ASCII):
        raise argparse.ArgumentTypeError(
            f"{valor!r} no cumple el formato cama-NN (dos dígitos, p. ej. "
            f"cama-09): es la ruta del video Y la clave que la web une con "
            f"los vitales."
        )
    return valor


def _resolucion(valor):
    m = re.fullmatch(r"(\d+)x(\d+)", valor, flags=re.ASCII)
    if not m or int(m.group(1)) <= 0 or int(m.group(2)) <= 0:
        raise argparse.ArgumentTypeError(
            f"{valor!r} no es una resolución ANCHOxALTO (p. ej. 1280x720 o "
            f"640x480)."
        )
    return (int(m.group(1)), int(m.group(2)))


def _bitrate(valor):
    # [1-9]: '0k'/'0M' pasarían la forma pero ffmpeg fallaría al arrancar, y
    # el supervisor lo reintentaría como si fuera un fallo de cámara/red —
    # un typo de configuración debe atraparlo el arranque estricto.
    if not re.fullmatch(r"[1-9]\d*[kM]", valor, flags=re.ASCII):
        raise argparse.ArgumentTypeError(
            f"{valor!r} no es un bitrate con sufijo k o M (p. ej. 2M, 800k)."
        )
    return valor


def _fps(valor):
    fps = int(valor)
    if fps <= 0:
        raise argparse.ArgumentTypeError("--fps debe ser positivo.")
    return fps


def _timeout_progreso(valor):
    v = float(valor)
    # nan/inf desactivarían el watchdog EN SILENCIO (toda comparación > nan es
    # False); <= 1 tick derribaría ffmpeg sanos en bucle. Ambos son el peligro
    # clínico exacto que el watchdog existe para impedir.
    if not math.isfinite(v) or v < 2.0:
        raise argparse.ArgumentTypeError(
            f"{valor!r} inválido para --timeout-progreso: se espera un número "
            f"finito >= 2 (segundos sin progreso antes de derribar)."
        )
    return v


def _senal_a_interrupcion(*_args):
    # SIGTERM -> el mismo camino de cierre limpio que Ctrl+C (KeyboardInterrupt
    # emerge del wait()/sleep del supervisor). Es el wiring para el systemd
    # futuro documentado en ADR-020.
    raise KeyboardInterrupt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m video.transmitir",
        description="Transmite la cámara de UNA cama a MediaMTX (RTSP) con "
                    "x264 de baja latencia, supervisado: se relanza solo si "
                    "el stream cae o se estanca (ADR-020)",
    )
    p.add_argument("--cama-id", type=_cama_id, required=False,
                   help="OBLIGATORIO (salvo --listar-dispositivos): cama-NN, "
                        "p. ej. cama-09. Es la ruta RTSP y la clave que une "
                        "video y vitales en la web")
    p.add_argument("--dispositivo", required=False,
                   help="OBLIGATORIO (salvo --listar-dispositivos): identidad "
                        "estable de la cámara — serial (35562055), fragmento "
                        "del by-id, o by-path/puerto físico (usb-0:2.2, para "
                        "webcams sin serial) — o ruta/índice literal "
                        "(/dev/videoN). Ver --listar-dispositivos")
    # El env se lee AQUÍ (no al importar el módulo): un orquestador que fije
    # RTSP_SERVIDOR tras el import debe surtir efecto. No se interpola el
    # valor en el help: argparse %-formatea y un '%' en el env lo rompería.
    p.add_argument("--servidor",
                   default=os.environ.get("RTSP_SERVIDOR", "100.110.157.112"),
                   help="host de MediaMTX (RTSP); hoy la misma máquina que "
                        "el broker MQTT, pero este flag es del VIDEO "
                        "(def. 100.110.157.112, o el env RTSP_SERVIDOR)")
    p.add_argument("--puerto-rtsp", type=int, default=8554)
    p.add_argument("--resolucion", type=_resolucion, default="1280x720",
                   help="ANCHOxALTO (def. 1280x720; perfil bajo: 640x480)")
    p.add_argument("--fps", type=_fps, default=25)
    p.add_argument("--bitrate", type=_bitrate, default="2M",
                   help="bitrate CBR con sufijo k/M (def. 2M; perfil bajo: 800k)")
    p.add_argument("--formato-entrada", default="mjpeg",
                   help="formato de captura V4L2 (def. mjpeg: crudo YUYV "
                        "corrompe buffers por USB; 'none' no fuerza formato)")
    p.add_argument("--timeout-progreso", type=_timeout_progreso,
                   default=transmisor.TIMEOUT_PROGRESO_S,
                   help=f"segundos sin progreso de ffmpeg antes de derribar y "
                        f"relanzar (finito, >= 2; def. "
                        f"{transmisor.TIMEOUT_PROGRESO_S:.0f})")
    p.add_argument("--una-vez", action="store_true",
                   help="un solo lanzamiento sin supervisión (depuración); "
                        "sale con el código de ffmpeg")
    p.add_argument("--listar-dispositivos", action="store_true",
                   help="lista las cámaras V4L2 detectadas (nombre, serial, "
                        "by-id, by-path, nodo de captura) y sale")
    args = p.parse_args(argv)

    # --listar-dispositivos corta ANTES de cualquier resolución/preflight:
    # es la herramienta para descubrir la identidad, debe funcionar sola.
    if args.listar_dispositivos:
        from ocr.dispositivos import formatear_tabla, listar_dispositivos
        try:
            dispositivos = listar_dispositivos()
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1
        print(formatear_tabla(dispositivos))
        if not any(d.nodo_captura for d in dispositivos):
            print("Ningún dispositivo con nodo de captura detectado.")
            return 1
        return 0

    if args.cama_id is None or args.dispositivo is None:
        p.error("--cama-id y --dispositivo son obligatorios (salvo con "
                "--listar-dispositivos)")

    # Preflight del entorno: sin ffmpeg no hay nada que supervisar. Fallar
    # aquí con mensaje accionable, no con un FileNotFoundError críptico.
    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg no está en el PATH. Instálalo (sudo apt install "
              "ffmpeg) y relanza.")
        return 1

    ancho, alto = args.resolucion
    try:
        supervisor = transmisor.SupervisorTransmision(
            dispositivo=args.dispositivo,
            cama_id=args.cama_id,
            servidor=args.servidor,
            puerto=args.puerto_rtsp,
            ancho=ancho,
            alto=alto,
            fps=args.fps,
            bitrate=args.bitrate,
            formato_entrada=args.formato_entrada,
            timeout_progreso=args.timeout_progreso,
        )
    except (transmisor.TransmisionFatal, RuntimeError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1

    # El handler de SIGTERM se instala solo mientras corre el supervisor y se
    # restaura al salir: main() no debe filtrar estado global de señales al
    # proceso que lo llame (pytest, un orquestador futuro).
    handler_previo = None
    try:
        handler_previo = signal.signal(signal.SIGTERM, _senal_a_interrupcion)
    except (ValueError, OSError):
        pass  # plataforma sin SIGTERM o hilo no principal: Ctrl+C sigue OK

    # Fallos de arranque (identidad ausente/ambigua, ffmpeg desaparecido) y
    # fatales de corrida (nodo literal que ahora es OTRA cámara) salen con
    # mensaje accionable y código 1, no un traceback (patrón ocr.publicar).
    try:
        if args.una_vez:
            return supervisor.una_vez()
        supervisor.correr()
        return 0
    except (transmisor.TransmisionFatal, RuntimeError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        if handler_previo is not None:
            try:
                signal.signal(signal.SIGTERM, handler_previo)
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    sys.exit(main())
