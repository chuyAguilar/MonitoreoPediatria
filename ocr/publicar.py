"""Runner del puente OCR → MQTT: lee frames en bucle y publica el contrato.

Captura EN VIVO desde la capturadora (en la Jetson; requiere PaddleOCR):
    python -m ocr.publicar --fuente capturadora --dispositivo /dev/video0 \
        --broker 100.110.157.112 --cama-id cama-09

Imagen fija (default, retrocompatible):
    python -m ocr.publicar --broker 100.110.157.112 --cama-id cama-01

Solo transporte, sin PaddleOCR (los valores van null, valida MQTT/estado/web):
    python -m ocr.publicar --motor plantilla --cama-id cama-01

Sin broker, imprime el JSON en consola (prueba rápida):
    python -m ocr.publicar --motor plantilla --solo-consola

Detener: Ctrl+C (publica la cama como offline y libera la capturadora).
"""

import argparse
import json
import os
import sys
import time

import ocr
from ocr.fuente import FuenteCapturadora, FuenteImagenFija
from ocr.lector import leer_imagen, motor_por_defecto
from ocr.perfiles import cargar_perfil
from ocr.publicador import PublicadorOCR, crear_cliente_mqtt
from ocr.tiempo import ahora_iso

_DIR_SIMCORE = os.path.join(os.path.dirname(ocr.__file__), "perfiles", "simcore")
FRAME_DEFECTO = os.path.join(_DIR_SIMCORE, "frame_simcore.png")
PERFIL_DEFECTO = os.path.join(_DIR_SIMCORE, "simcore.json")
BROKER_DEFECTO = os.environ.get("MQTT_BROKER", "100.110.157.112")


def correr(fuente, motor, perfil, cama_id, device_id, publicador, hz=1.0, max_ticks=None):
    """Bucle principal: online → (frame → OCR → publicar)* → offline.

    Solo re-ejecuta el OCR cuando la fuente dice que hay frame nuevo (`cambio()`);
    en los demás ticks republica la última lectura con un `ts` fresco, lo que
    mantiene la cama viva en el dashboard sin re-OCR-ar una imagen que no cambió.
    `max_ticks` acota el bucle en los tests (None = infinito).
    """
    periodo = 1.0 / hz if hz > 0 else 0.0
    ultimo = None
    ticks = 0
    try:
        publicador.publicar_estado("online")   # dentro del try: el finally cierra igual
        while max_ticks is None or ticks < max_ticks:
            t0 = time.monotonic()
            # `cambio()` se consulta SIEMPRE (tiene estado: consume su "primera
            # vez"); el `ultimo is None` es solo una red por si una fuente
            # devolviera cambio()=False antes de la primera lectura.
            hay_nuevo = fuente.cambio()
            if ultimo is None or hay_nuevo:
                ultimo = leer_imagen(fuente.frame(), perfil, cama_id, device_id, motor=motor)
            # `ts` fresco en cada publicación (incluida la republicación cacheada);
            # `pni.ts` queda como lo leyó el OCR (medición real de la presión).
            publicador.publicar_vitales({**ultimo, "ts": ahora_iso()})
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            dormir = periodo - (time.monotonic() - t0)
            if dormir > 0:
                time.sleep(dormir)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        # `offline` es la señal clínica (la cama desconectada en la web): se
        # publica PRIMERO y protegido, para que salga aunque liberar la fuente
        # falle (importará cuando la fuente sea la capturadora en vivo).
        try:
            publicador.cerrar()
        finally:
            fuente.cerrar()


def _construir_motor(nombre):
    if nombre == "plantilla":
        from ocr.motor.plantilla import LectorPlantilla
        return LectorPlantilla()
    return motor_por_defecto()  # producción; falla fuerte si PaddleOCR no está


class _ClienteConsola:
    """Cliente MQTT falso que imprime en vez de publicar (para --solo-consola)."""

    def publish(self, topic, payload, qos=0, retain=False):
        print(f"{topic}  {payload}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m ocr.publicar",
        description="Publica por MQTT los signos leídos por OCR de un frame (contrato 1.1)",
    )
    p.add_argument("--broker", default=BROKER_DEFECTO, help=f"IP del broker MQTT (def. {BROKER_DEFECTO})")
    p.add_argument("--puerto-broker", type=int, default=1883)
    p.add_argument("--cama-id", default="cama-01")
    p.add_argument("--device-id", default="jetson-01")
    p.add_argument("--hz", type=float, default=1.0, help="frecuencia de publicación (def. 1.0)")
    p.add_argument("--fuente", choices=("imagen", "capturadora"), default="imagen",
                   help="imagen = frame fijo (def.); capturadora = captura V4L2 en vivo")
    p.add_argument("--dispositivo", default="/dev/video0",
                   help="dispositivo V4L2 para --fuente capturadora (def. /dev/video0)")
    p.add_argument("--imagen", default=FRAME_DEFECTO, help="frame fijo a leer (def. frame de SimCore)")
    p.add_argument("--perfil", default=PERFIL_DEFECTO, help="perfil de ROIs (def. simcore.json)")
    p.add_argument("--motor", choices=("produccion", "plantilla"), default="produccion",
                   help="produccion = PaddleOCR (def.); plantilla = solo transporte (valores null)")
    p.add_argument("--solo-consola", action="store_true", help="imprime el JSON en vez de publicar (sin broker)")
    args = p.parse_args(argv)

    # Fallos de arranque (imagen/perfil ilegible, capturadora que no abre o
    # entrega otra resolución, PaddleOCR no instalado) salen con un mensaje
    # claro y código 1, no un traceback. Si algo falla DESPUÉS de abrir la
    # capturadora, el dispositivo se libera antes de salir.
    fuente = None
    try:
        if args.fuente == "capturadora":
            fuente = FuenteCapturadora(args.dispositivo)
        else:
            fuente = FuenteImagenFija(args.imagen)
        perfil = cargar_perfil(args.perfil)
        motor = _construir_motor(args.motor)
    except (RuntimeError, ValueError, OSError) as e:
        # OSError cubre FileNotFoundError (perfil o imagen inexistentes)
        if fuente is not None:
            fuente.cerrar()
        print(f"ERROR: {e}")
        return 1

    if args.solo_consola:
        cliente = _ClienteConsola()
        print(f"OCR -> CONSOLA (sin MQTT). cama={args.cama_id} motor={args.motor}")
    else:
        try:
            cliente = crear_cliente_mqtt(args.broker, args.puerto_broker, client_id=f"ocr-{args.cama_id}")
        except (OSError, RuntimeError) as e:
            fuente.cerrar()
            print(f"ERROR: no se pudo crear/conectar el cliente MQTT {args.broker}:{args.puerto_broker}: {e}")
            print("¿Está Mosquitto corriendo? ¿Está paho-mqtt instalado? Ver docs/ito2/SIMULADOR.md")
            return 1
        print(f"OCR -> MQTT {args.broker}:{args.puerto_broker}  cama={args.cama_id} motor={args.motor}")

    print(f"Fuente: {fuente}. Ctrl+C para detener.\n")
    correr(fuente, motor, perfil, args.cama_id, args.device_id, PublicadorOCR(args.cama_id, args.device_id, cliente), hz=args.hz)
    print("Detenido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
