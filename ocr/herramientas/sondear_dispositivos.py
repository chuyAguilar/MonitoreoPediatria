"""Sonda de dispositivos V4L2: qué hay conectado y con qué identidad estable.

Herramienta de campo (Linux/Jetson). Imprime, por dispositivo físico: nombre
de tarjeta, identidad `by-id` (con el serial), puerto físico `by-path`, y cada
nodo /dev/videoN con sus capacidades reales según VIDIOC_QUERYCAP (captura vs
metadatos). Al final sugiere el identificador a fijar en el publicador.

Es la versión empaquetada de la sonda con la que se verificó la convención del
target en la iteración 7 (ADR-018), y el primer paso del diagnóstico cuando
"todos los signos salen null": ¿de verdad estás leyendo la capturadora?

Uso (en la Jetson):
    python -m ocr.herramientas.sondear_dispositivos
"""

import sys

from ocr.dispositivos import (
    V4L2_CAP_VIDEO_CAPTURE,
    formatear_tabla,
    listar_dispositivos,
)


def main() -> int:
    try:
        dispositivos = listar_dispositivos()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    if not dispositivos:
        print("No se detectó ningún dispositivo de video V4L2.")
        print("¿Está conectada la capturadora? ¿Permisos del grupo 'video'?")
        return 1

    print(f"{len(dispositivos)} dispositivo(s) de video detectado(s):\n")
    print(formatear_tabla(dispositivos))

    con_captura = [d for d in dispositivos if d.nodo_captura]
    if con_captura:
        print("\nPara fijar la capturadora por identidad estable en el publicador:")
        for d in con_captura:
            identificador = d.serial or d.by_id or d.nombre
            if identificador:
                print(f"  python -m ocr.publicar --fuente capturadora "
                      f"--dispositivo {identificador!r} ...")
    else:
        print("\nNingún dispositivo expone un nodo con capacidad de captura.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
