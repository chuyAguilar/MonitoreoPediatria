"""Runner de la ingesta de vitales: Mosquitto → SQLite (ADR-021).

En el servidor (como servicio; ver persistencia/vitales-ingest.service):
    python -m persistencia.ingerir

Desarrollo local (broker y BD propios):
    python -m persistencia.ingerir --broker localhost --bd data/vitales.db

Solo crear/verificar el esquema y salir (para el despliegue de alfred):
    python -m persistencia.ingerir --bd /home/chuy/datos/monitoreo/vitales.db --solo-esquema

Detener: Ctrl+C o SIGTERM (systemd) — vacía el lote pendiente antes de salir.
Env vars (se leen al ejecutar, no al importar): INGESTA_BROKER, INGESTA_PUERTO,
INGESTA_BD, INGESTA_LOTE, INGESTA_INTERVALO.

La BD contiene DATOS DE PACIENTES: en el servidor vive FUERA del working tree
de git (un `git clean -fdx` borra hasta lo ignorado); el default relativo
`data/` es solo para desarrollo. Ver ADR-021.
"""

import argparse
import math
import os
import signal
import sqlite3
import sys

from persistencia import ingestor
from persistencia.almacen import AlmacenVitales


def _lote(valor):
    try:
        n = int(valor)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{valor!r} no es un entero.")
    if n < 1:
        # --lote 0 degeneraría en un commit por mensaje: derrota la única
        # razón de ser del lote en la eMMC. Typo de config = arranque estricto.
        raise argparse.ArgumentTypeError(
            f"--lote debe ser >= 1 (con {n} cada mensaje haría su propio "
            f"commit, castigando la eMMC)."
        )
    return n


def _intervalo(valor):
    try:
        v = float(valor)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{valor!r} no es un número.")
    if not math.isfinite(v) or v <= 0:
        raise argparse.ArgumentTypeError(
            f"--intervalo debe ser un número finito > 0 (segundos entre "
            f"vaciados del lote); {valor!r} no lo es."
        )
    return v


def _senal_a_interrupcion(*_args):
    # SIGTERM (systemd stop) -> el mismo cierre limpio que Ctrl+C.
    raise KeyboardInterrupt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m persistencia.ingerir",
        description="Se suscribe a Mosquitto y persiste todo mensaje de "
                    "vitales y estado en SQLite (WAL + lotes; ADR-021)",
    )
    # Los defaults de env se resuelven AQUÍ y como string: argparse les aplica
    # type=, así que un env con basura cae en el mismo error accionable.
    p.add_argument("--broker",
                   default=os.environ.get("INGESTA_BROKER", "localhost"),
                   help="broker MQTT (def. localhost — la ingesta corre EN el "
                        "servidor; env INGESTA_BROKER)")
    p.add_argument("--puerto-broker", type=int,
                   default=os.environ.get("INGESTA_PUERTO", "1883"),
                   help="def. 1883 (env INGESTA_PUERTO)")
    p.add_argument("--bd",
                   default=os.environ.get("INGESTA_BD", "data/vitales.db"),
                   help="ruta del archivo SQLite (def. data/vitales.db — SOLO "
                        "desarrollo; en el servidor va FUERA del working tree, "
                        "env INGESTA_BD)")
    p.add_argument("--lote", type=_lote,
                   default=os.environ.get("INGESTA_LOTE", str(ingestor.LOTE_DEFECTO)),
                   help=f"N mensajes que fuerzan el vaciado "
                        f"(def. {ingestor.LOTE_DEFECTO}; env INGESTA_LOTE)")
    p.add_argument("--intervalo", type=_intervalo,
                   default=os.environ.get("INGESTA_INTERVALO",
                                          str(ingestor.INTERVALO_DEFECTO_S)),
                   help=f"T segundos entre vaciados "
                        f"(def. {ingestor.INTERVALO_DEFECTO_S:.0f}; env "
                        f"INGESTA_INTERVALO)")
    p.add_argument("--solo-esquema", action="store_true",
                   help="crea/verifica la BD y el esquema, y sale (paso de "
                        "despliegue verificable)")
    args = p.parse_args(argv)

    try:
        almacen = AlmacenVitales(args.bd)
    except (OSError, sqlite3.Error) as e:
        print(f"ERROR: no se pudo abrir/crear la BD {args.bd!r}: {e}")
        print("¿Existe el directorio y tiene permisos el usuario del servicio?")
        return 1

    print(f"[ingesta] BD {almacen.ruta} (journal={almacen.journal_mode}, "
          f"esquema v{almacen.version_esquema})", flush=True)

    if args.solo_esquema:
        almacen.cerrar()
        print("[ingesta] esquema listo; saliendo (--solo-esquema).")
        return 0

    servicio = ingestor.ServicioIngesta(
        almacen, lote=args.lote, intervalo_s=args.intervalo,
    )
    try:
        cliente = ingestor.crear_cliente_suscriptor(
            args.broker, args.puerto_broker, servicio,
        )
    except (OSError, RuntimeError) as e:
        almacen.cerrar()
        print(f"ERROR: no se pudo conectar el suscriptor MQTT a "
              f"{args.broker}:{args.puerto_broker}: {e}")
        print("¿Está Mosquitto corriendo? (En el boot, systemd reintenta: "
              "After=mosquitto + Restart=on-failure.)")
        return 1

    # Handler de SIGTERM instalado solo mientras corre el servicio, y
    # restaurado al salir (no filtrar estado global a pytest/orquestadores).
    handler_previo = None
    try:
        handler_previo = signal.signal(signal.SIGTERM, _senal_a_interrupcion)
    except (ValueError, OSError):
        pass

    print(f"[ingesta] suscrito a {ingestor.SUSCRIPCION_VITALES} y "
          f"{ingestor.SUSCRIPCION_ESTADO} en {args.broker}:"
          f"{args.puerto_broker} (lote={args.lote}, intervalo="
          f"{args.intervalo:g}s). Ctrl+C para detener.", flush=True)
    try:
        servicio.correr()  # Ctrl+C/SIGTERM se atrapan dentro; retorna limpio
        return 0
    except RuntimeError as e:
        # CONNACK/SUBACK rechazado repetido: salir con error VISIBLE (systemd
        # reinicia y el fallo queda en journald), no "active" sin ingerir.
        print(f"ERROR: {e}")
        return 1
    finally:
        # Orden del cierre: primero deja de LLEGAR (loop_stop), luego el
        # vaciado final (protegido de una segunda señal), luego cerrar la BD.
        # El handler de SIGTERM se restaura AL FINAL: si se restaurara antes,
        # un segundo SIGTERM durante el vaciado mataría el proceso a mitad
        # del flush y perdería filas ya PUBACKeadas al broker.
        try:
            ingestor.apagar_cliente(cliente)
        except KeyboardInterrupt:
            try:
                ingestor.apagar_cliente(cliente)
            except KeyboardInterrupt:
                pass  # seguir al vaciado final pase lo que pase
        try:
            servicio.vaciar_final()
        finally:
            almacen.cerrar()
            if handler_previo is not None:
                try:
                    signal.signal(signal.SIGTERM, handler_previo)
                except (ValueError, OSError):
                    pass
        print("[ingesta] Detenido.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
