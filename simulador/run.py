"""Simulador de monitoreo pediátrico multi-cama.

Al ejecutar:
  1. Detecta las cámaras web conectadas.
  2. Pregunta cuántas camas simular.
  3. Pregunta a qué cama va cada cámara (o usa el mapeo dado por línea de comandos).
  4. Inicia la simulación: publica signos vitales por MQTT (formato del contrato)
     y transmite el video de cada cámara por RTSP al servidor, con su cama asignada.

Uso interactivo:
    python run.py

Uso no interactivo / pruebas:
    python run.py --camas 4                          # pregunta el mapeo de cámaras
    python run.py --camas 4 --camara video0:3        # /dev/video0 -> cama-03
    python run.py --camas 4 --camara 0:3 --camara 2:1
    python run.py --camas 3 --sin-video              # solo datos
    python run.py --camas 2 --sin-video --solo-consola

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


def pedir_int(mensaje, defecto, minimo=0, maximo=None):
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
        if valor < minimo or (maximo is not None and valor > maximo):
            rango = f">= {minimo}" if maximo is None else f"entre {minimo} y {maximo}"
            print(f"  Debe ser {rango}.")
            continue
        return valor


def _num_a_cama(txt, cama_ids):
    txt = txt.strip()
    cama_id = f"cama-{int(txt):02d}" if txt.isdigit() else txt
    return cama_id if cama_id in cama_ids else None


def _buscar_camara(dev, detectadas):
    for idx, ruta, nombre in detectadas:
        if dev.isdigit() and int(dev) == idx:
            return (idx, ruta, nombre)
        ruta_norm = dev if dev.startswith("/dev/") else f"/dev/{dev}"
        if ruta_norm == ruta:
            return (idx, ruta, nombre)
    return None


def asignar_por_cli(entradas, detectadas, cama_ids):
    asignacion = {}
    for entrada in entradas:
        dev, _, cama = entrada.partition(":")
        cama_id = _num_a_cama(cama, cama_ids)
        if cama_id is None:
            print(f"  Aviso: cama inválida en '{entrada}', se omite.")
            continue
        camara = _buscar_camara(dev.strip(), detectadas)
        if camara is None:
            print(f"  Aviso: cámara '{dev}' no detectada, se omite.")
            continue
        asignacion[cama_id] = camara
    return asignacion


def asignar_interactivo(detectadas, cama_ids):
    asignacion = {}
    n = len(cama_ids)
    print("\nAsigna cada cámara a una cama (0 = no usar):")
    for pos, (idx, ruta, nombre) in enumerate(detectadas):
        sugerido = pos + 1 if pos + 1 <= n else 0
        while True:
            elegida = pedir_int(f"  {ruta} ({nombre}) -> cama (1-{n}, 0=no usar)", sugerido, 0, n)
            if elegida == 0:
                break
            cama_id = f"cama-{elegida:02d}"
            if cama_id in asignacion:
                print(f"  {cama_id} ya tiene una cámara, elige otra.")
                continue
            asignacion[cama_id] = (idx, ruta, nombre)
            break
    return asignacion


def estado_msg(cama_id, estado):
    return json.dumps(
        {"cama_id": cama_id, "device_id": DEVICE_ID, "estado": estado, "ts": ahora_iso()}
    )


def main():
    p = argparse.ArgumentParser(description="Simulador de monitores de signos vitales (multi-cama)")
    p.add_argument("--camas", type=int, help="número de camas a simular (omitir = preguntar)")
    p.add_argument("--camara", action="append", default=[], metavar="DEV:CAMA",
                   help="asigna una cámara a una cama, ej. video0:3 o 0:3 (repetible)")
    p.add_argument("--camaras", type=int, help="atajo: primeras K cámaras en las primeras K camas")
    p.add_argument("--server", default="100.110.157.112", help="IP del servidor (broker MQTT + RTSP)")
    p.add_argument("--broker", help="IP del broker MQTT (por defecto = --server)")
    p.add_argument("--puerto-broker", type=int, default=1883)
    p.add_argument("--sin-video", action="store_true", help="no transmitir video, solo datos")
    p.add_argument("--solo-consola", action="store_true", help="imprime JSON en consola en vez de MQTT")
    p.add_argument("--hz", type=float, default=1.0, help="frecuencia de publicación de datos")
    p.add_argument("--ancho", type=int, default=640)
    p.add_argument("--alto", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--formato-entrada", default="mjpeg",
                   help="formato de captura de la webcam (mjpeg por defecto; 'none' para no forzar)")
    args = p.parse_args()

    broker = args.broker or args.server
    print("=== Simulador de monitoreo pediátrico (multi-cama) ===\n")

    detectadas = []
    if args.sin_video:
        print("Video deshabilitado (--sin-video).")
    else:
        print("Detectando cámaras conectadas...")
        detectadas = detectar_camaras()
        if detectadas:
            for _idx, ruta, nombre in detectadas:
                print(f"  - {ruta}  ({nombre})")
        else:
            print("  No se detectaron cámaras.")

    if args.camas is not None:
        n_camas = max(1, args.camas)
    else:
        n_camas = pedir_int("\n¿Cuántas camas simular?", max(1, len(detectadas)), 1)
    cama_ids = [f"cama-{i:02d}" for i in range(1, n_camas + 1)]

    if not detectadas:
        asignacion = {}
    elif args.camara:
        asignacion = asignar_por_cli(args.camara, detectadas, cama_ids)
    elif args.camaras is not None:
        k = min(args.camaras, len(detectadas), n_camas)
        asignacion = {cama_ids[i]: detectadas[i] for i in range(k)}
    else:
        asignacion = asignar_interactivo(detectadas, cama_ids)

    print(f"\nSimulando {n_camas} cama(s): {', '.join(cama_ids)}")
    if asignacion:
        for cama_id, (_idx, ruta, _nombre) in sorted(asignacion.items()):
            print(f"  video: {cama_id} <- {ruta}")
    if args.solo_consola:
        print("Datos -> CONSOLA (sin MQTT).")
    else:
        print(f"Datos -> MQTT {broker}:{args.puerto_broker}")
        if asignacion:
            print(f"Video -> RTSP {args.server}:8554")
    print()

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

    generadores = {cid: GeneradorSignos(semilla=i) for i, cid in enumerate(cama_ids, 1)}

    procesos_video = []
    for cama_id, (_idx, ruta, _nombre) in asignacion.items():
        print(f"Iniciando video {ruta} -> {cama_id}")
        procesos_video.append(
            iniciar_video_webcam(ruta, cama_id, args.server, args.ancho, args.alto,
                                 args.fps, formato_entrada=args.formato_entrada)
        )

    if cliente:
        for cama_id in cama_ids:
            cliente.publish(f"monitoreo/estado/{cama_id}", estado_msg(cama_id, "online"), qos=1, retain=True)

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
