"""Simulador de monitoreo pediátrico multi-cama.

Al ejecutar:
  1. Detecta las cámaras web conectadas y pregunta cuántas usar.
  2. Pregunta cuántas camas simular.
  3. Inicia la simulación: publica signos vitales por MQTT (formato del contrato)
     y, para las camas con cámara, transmite el video por RTSP al servidor.

Uso interactivo:
    python run.py

Uso no interactivo / pruebas:
    python run.py --camas 4 --camaras 2
    python run.py --camas 3 --sin-video                 # solo datos
    python run.py --camas 2 --sin-video --solo-consola  # sin broker, imprime JSON

Detener: Ctrl+C
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from signos import GeneradorSignos, ahora_iso  # noqa: E402
from camaras import detectar_camaras  # noqa: E402
from video import iniciar_video_webcam  # noqa: E402

DEVICE_ID = "edge-01"


def pedir_int(mensaje: str, defecto: int, minimo: int = 0) -> int:
    while True:
        try:
            txt = input(f"{mensaje} [{defecto}]: ").strip()
        except EOFError:
            return defecto
        if txt == "":
            return defecto
        try:
            valor = int(txt)
        except ValueError:
            print("  Ingresa un número.")
            continue
        if valor < minimo:
            print(f"  Debe ser >= {minimo}.")
            continue
        return valor


def estado_msg(cama_id: str, estado: str) -> str:
    return json.dumps(
        {"cama_id": cama_id, "device_id": DEVICE_ID, "estado": estado, "ts": ahora_iso()}
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Simulador de monitores de signos vitales (multi-cama)")
    p.add_argument("--camas", type=int, help="número de camas a simular (omitir = preguntar)")
    p.add_argument("--camaras", type=int, help="cámaras a usar (omitir = detectar y preguntar)")
    p.add_argument("--server", default="100.110.157.112", help="IP del servidor (broker MQTT + RTSP)")
    p.add_argument("--broker", help="IP del broker MQTT (por defecto = --server)")
    p.add_argument("--puerto-broker", type=int, default=1883)
    p.add_argument("--sin-video", action="store_true", help="no transmitir video, solo datos")
    p.add_argument("--solo-consola", action="store_true", help="imprime JSON en consola en vez de MQTT")
    p.add_argument("--hz", type=float, default=1.0, help="frecuencia de publicación de datos")
    p.add_argument("--ancho", type=int, default=640)
    p.add_argument("--alto", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    args = p.parse_args()

    broker = args.broker or args.server

    print("=== Simulador de monitoreo pediátrico (multi-cama) ===\n")

    # ------------------------------------------------------------------
    # 1. Cámaras
    # ------------------------------------------------------------------
    camaras: list[tuple[int, str, str]] = []
    if args.sin_video:
        print("Video deshabilitado (--sin-video).")
    else:
        print("Detectando cámaras conectadas...")
        detectadas = detectar_camaras()
        if detectadas:
            for _idx, ruta, nombre in detectadas:
                print(f"  • {ruta}  ({nombre})")
        else:
            print("  No se detectaron cámaras.")
        n_detect = len(detectadas)
        if args.camaras is not None:
            n_cam = min(args.camaras, n_detect)
        else:
            n_cam = min(pedir_int("¿Cuántas cámaras usar?", n_detect, 0), n_detect)
        camaras = detectadas[:n_cam]

    # ------------------------------------------------------------------
    # 2. Camas
    # ------------------------------------------------------------------
    if args.camas is not None:
        n_camas = max(1, args.camas)
    else:
        sugerido = max(1, len(camaras))
        n_camas = pedir_int("¿Cuántas camas simular?", sugerido, 1)

    cama_ids = [f"cama-{i:02d}" for i in range(1, n_camas + 1)]

    # ------------------------------------------------------------------
    # 3. Resumen
    # ------------------------------------------------------------------
    print(f"\nSimulando {n_camas} cama(s): {', '.join(cama_ids)}")
    if camaras:
        print(f"Con video real: {len(camaras)} (las demás solo datos).")
    if args.solo_consola:
        print("Datos → CONSOLA (sin MQTT).")
    else:
        print(f"Datos → MQTT {broker}:{args.puerto_broker}")
        if camaras:
            print(f"Video → RTSP {args.server}:8554")
    print()

    # ------------------------------------------------------------------
    # 4. Conexión MQTT
    # ------------------------------------------------------------------
    cliente = None
    if not args.solo_consola:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("ERROR: falta paho-mqtt. Instala: pip install paho-mqtt")
            return
        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulador-monitoreo")
        try:
            cliente.connect(broker, args.puerto_broker, keepalive=60)
        except OSError as e:
            print(f"ERROR: no se pudo conectar al broker MQTT {broker}:{args.puerto_broker}: {e}")
            print("¿Está Mosquitto corriendo en el servidor? Ver docs/ito2/SIMULADOR.md")
            return
        cliente.loop_start()

    # ------------------------------------------------------------------
    # 5. Generadores y video
    # ------------------------------------------------------------------
    generadores = {cid: GeneradorSignos(semilla=i) for i, cid in enumerate(cama_ids, 1)}

    procesos_video = []
    if camaras:
        for (_idx, ruta, _nombre), cama_id in zip(camaras, cama_ids):
            print(f"Iniciando video {ruta} → {cama_id}")
            procesos_video.append(
                iniciar_video_webcam(ruta, cama_id, args.server, args.ancho, args.alto, args.fps)
            )

    if cliente:
        for cama_id in cama_ids:
            cliente.publish(f"monitoreo/estado/{cama_id}", estado_msg(cama_id, "online"), qos=1, retain=True)

    # ------------------------------------------------------------------
    # 6. Bucle de simulación
    # ------------------------------------------------------------------
    print("\nSimulación corriendo. Ctrl+C para detener.\n")
    periodo = 1.0 / args.hz
    try:
        while True:
            for cama_id in cama_ids:
                gen = generadores[cama_id]
                gen.paso(periodo)
                carga = json.dumps(gen.construir_mensaje(cama_id, DEVICE_ID))
                if args.solo_consola:
                    print(carga)
                else:
                    cliente.publish(f"monitoreo/vitales/{cama_id}", carga, qos=1, retain=True)
            time.sleep(periodo)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        for proc in procesos_video:
            proc.terminate()
        if cliente:
            for cama_id in cama_ids:
                cliente.publish(f"monitoreo/estado/{cama_id}", estado_msg(cama_id, "offline"), qos=1, retain=True)
            time.sleep(0.3)
            cliente.loop_stop()
            cliente.disconnect()
        print("Detenido.")


if __name__ == "__main__":
    main()
