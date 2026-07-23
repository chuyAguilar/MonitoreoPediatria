"""CLI del módulo OCR: lee una imagen fija y emite el JSON del contrato 1.1.

Ejemplo:
    python -m ocr.cli --imagen captura.png --perfil ocr/perfiles/monitor_mock.json \
        --cama-id cama-01 --device-id jetson-01
"""

import argparse
import json
import sys
from pathlib import Path

from ocr.lector import leer_imagen


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ocr.cli",
        description="Lee signos vitales de una imagen de monitor y emite el contrato 1.1",
    )
    parser.add_argument("--imagen", required=True, help="Ruta a la imagen PNG/JPG")
    parser.add_argument("--perfil", required=True, help="Ruta al perfil JSON de ROIs")
    parser.add_argument("--cama-id", required=True, help="Ej. cama-01")
    parser.add_argument("--device-id", required=True, help="Ej. jetson-01")
    parser.add_argument("--salida", help="Además de imprimir, escribe el JSON a este archivo")
    args = parser.parse_args(argv)

    mensaje = leer_imagen(args.imagen, args.perfil, args.cama_id, args.device_id)
    texto = json.dumps(mensaje, ensure_ascii=False, indent=2)
    if args.salida:
        Path(args.salida).write_text(texto + "\n", encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
