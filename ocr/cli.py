"""CLI del módulo OCR: lee una imagen fija y emite el JSON del contrato 1.1.

Ejemplo (motor de producción, requiere ocr/requirements-motor.txt instalado):
    python -m ocr.cli --imagen captura.png --perfil ocr/perfiles/simcore/simcore.json \
        --cama-id cama-01 --device-id jetson-01

Para el mock sintético sin instalar el motor real, usa el andamiaje de plantilla:
    python -m ocr.cli --imagen monitor_mock.png --perfil ocr/perfiles/monitor_mock.json \
        --cama-id cama-01 --device-id jetson-01 --motor plantilla
"""

import argparse
import json
import sys
from pathlib import Path

from ocr.lector import leer_imagen, motor_por_defecto


def _construir_motor(nombre):
    if nombre == "plantilla":
        # Andamiaje: NO lee monitores reales, solo el mock sintético (ADR-014).
        from ocr.motor.plantilla import LectorPlantilla
        return LectorPlantilla()
    return motor_por_defecto()  # producción; falla fuerte si no está instalado


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
    parser.add_argument(
        "--motor", choices=("produccion", "plantilla"), default="produccion",
        help="produccion = PaddleOCR (defecto); plantilla = andamiaje para el mock",
    )
    args = parser.parse_args(argv)

    motor = _construir_motor(args.motor)
    mensaje = leer_imagen(args.imagen, args.perfil, args.cama_id, args.device_id, motor=motor)
    texto = json.dumps(mensaje, ensure_ascii=False, indent=2)
    if args.salida:
        Path(args.salida).write_text(texto + "\n", encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
