"""Publicador MQTT del contrato: transporta lo que el lector ya validó.

Replica el patrón del simulador (paho-mqtt v2, QoS 1, retained, ciclo
online/offline) para que `ocr/` quede autocontenido y se despliegue solo en la
Jetson, sin depender de `simulador/` (que vive en otra máquina). Ver el brief
§5 de la iteración 4.

El publicador es SOLO transporte: publica exactamente el mensaje que
`ocr.lector.leer_imagen` devolvió, `null` incluidos. No reinterpreta ni valida
signos — las salvaguardas del OCR ya mandaron aguas arriba.

El cliente MQTT se INYECTA (no lo crea la clase), para poder probar sin broker
con un cliente falso. La CLI usa `crear_cliente_mqtt()` para el cliente real,
que además configura el Last Will (ADR-022): si el edge muere de golpe, el
BROKER publica el offline retenido — el mismo payload que publicar_estado,
por construcción — y on_connect re-publica online en cada (re)conexión.
"""

import json
import time

from ocr.tiempo import ahora_iso

TOPIC_VITALES = "monitoreo/vitales/{cama_id}"
TOPIC_ESTADO = "monitoreo/estado/{cama_id}"

# Keepalive del cliente (ADR-022): ante muerte SILENCIOSA del edge (corte de
# energía, cable), el broker dispara el Last Will a ~1.5×keepalive — con 15 s,
# ~22 s de "online" falso en vez de ~90 s. El costo es ≈ cero: con vitales a
# 1 Hz los publishes+PUBACKs son el keepalive efectivo y el PINGREQ solo
# aparece si el pipeline calla >15 s. (La muerte del PROCESO — kill -9,
# crash — cierra el socket sin DISCONNECT y dispara el will de inmediato.)
KEEPALIVE_S = 15


def carga_estado(cama_id: str, device_id: str, estado: str, ts: str) -> str:
    """El payload de estado del contrato — ÚNICO constructor.

    Lo usan publicar_estado() Y el Last Will (ADR-022): el offline que publica
    el broker ante una muerte súbita es idéntico al del apagado limpio POR
    CONSTRUCCIÓN, no por mantenimiento paralelo.
    """
    return json.dumps({
        "cama_id": cama_id,
        "device_id": device_id,
        "estado": estado,
        "ts": ts,
    }, ensure_ascii=False)


def will_de_estado(cama_id: str, device_id: str):
    """(topic, carga) del Last Will: offline con el ts del PRIMER connect.

    Caveat documentado (ADR-022): el payload del will se construye UNA vez,
    antes de la primera conexión (el arranque del runner), y paho re-manda
    ese payload TAL CUAL en cada reconexión automática — no se refresca
    (decisión aprobada: sin refresco cosmético). El instante de la muerte es
    incognoscible por diseño; el consumidor debe usar el `recibido_en` de la
    BD y el campo `estado`, nunca el `ts` del will, para razonar sobre CUÁNDO
    ocurrió la desconexión. Lo clínico es el ESTADO.
    """
    topic = TOPIC_ESTADO.format(cama_id=cama_id)
    return topic, carga_estado(cama_id, device_id, "offline", ahora_iso())


def al_conectar_republica_online(cama_id: str, device_id: str):
    """Callback on_connect (paho v2): re-publica `online` en cada (re)conexión.

    Sin esto, el LWT abre la mentira inversa: un blip de red > keepalive
    dispara el will (offline RETENIDO), paho reconecta solo, los vitales
    fluyen… y la cama viva queda marcada muerta para siempre. Mismo patrón que
    la re-suscripción del ingestor (ADR-021): lo que no se re-manda solo se
    rehace en on_connect (el will sí lo re-manda paho en cada CONNECT).

    Blindado como los callbacks del ingestor: firma VERSION2 de 5 argumentos,
    guard duck-typed del CONNACK fallido (on_connect también se invoca en el
    rechazo), y TODO el cuerpo bajo except — una excepción del callback mata
    el hilo de red de paho sin reconexión.
    """
    topic = TOPIC_ESTADO.format(cama_id=cama_id)

    def _al_conectar(cliente, _userdata, _flags, reason_code, _properties=None):
        global _conectado_desde
        try:
            if getattr(reason_code, "is_failure", False):
                print(f"[ocr] conexión MQTT rechazada por el broker "
                      f"({reason_code})", flush=True)
                return
            _conectado_desde = time.monotonic()
            print(f"[ocr] conectado al broker; re-publicando estado online",
                  flush=True)
            cliente.publish(
                topic, carga_estado(cama_id, device_id, "online", ahora_iso()),
                qos=1, retain=True,
            )
        except Exception as e:
            try:
                print(f"[ocr] error en on_connect: {e}", flush=True)
            except Exception:
                pass

    return _al_conectar


# Diagnóstico de takeover (ADR-022): dos publicadores con el MISMO client_id
# (doble arranque de la misma cama) se expulsan mutuamente — cada CONNECT del
# rival publica el will del expulsado (offline retenido) y produce flapping
# offline/online. El patrón visible: desconexiones inmediatas repetidas.
_conectado_desde = None
_desconexiones_rapidas = 0


def _al_desconectar(_cliente, _userdata, _flags, reason_code, _properties=None):
    """on_disconnect con log: los mensajes de reconexión internos de paho son
    nivel DEBUG y jamás llegarían a journald (lección de ADR-021)."""
    global _desconexiones_rapidas
    try:
        rapida = (_conectado_desde is not None
                  and time.monotonic() - _conectado_desde < KEEPALIVE_S)
        _desconexiones_rapidas = _desconexiones_rapidas + 1 if rapida else 0
        print(f"[ocr] desconectado del broker MQTT ({reason_code}); paho "
              f"reintenta solo", flush=True)
        if _desconexiones_rapidas >= 2:
            print("[ocr] AVISO: desconexiones inmediatas repetidas — ¿hay "
                  "OTRO publicador con el mismo client_id (la misma cama "
                  "lanzada dos veces)? El takeover mutuo produce flapping "
                  "offline/online del estado retenido.", flush=True)
    except Exception:
        pass


class PublicadorOCR:
    """Publica vitales y estado de una cama por MQTT (QoS 1, retained)."""

    def __init__(self, cama_id: str, device_id: str, cliente):
        self._cama_id = cama_id
        self._device_id = device_id
        self._cliente = cliente
        self._topic_vitales = TOPIC_VITALES.format(cama_id=cama_id)
        self._topic_estado = TOPIC_ESTADO.format(cama_id=cama_id)

    def publicar_vitales(self, mensaje: dict) -> None:
        """Publica el mensaje del contrato tal cual (sin tocar sus `null`)."""
        carga = json.dumps(mensaje, ensure_ascii=False)
        self._cliente.publish(self._topic_vitales, carga, qos=1, retain=True)

    def publicar_estado(self, estado: str) -> None:
        """Publica online/offline con el mismo formato que el simulador."""
        carga = carga_estado(self._cama_id, self._device_id, estado, ahora_iso())
        self._cliente.publish(self._topic_estado, carga, qos=1, retain=True)

    def cerrar(self) -> None:
        """Marca la cama offline (retained) y desconecta con limpieza.

        Que `offline` quede retenido hace que la web muestre la cama como
        desconectada de inmediato al cerrar, sin esperar al timeout de datos.
        """
        try:
            self.publicar_estado("offline")
        finally:
            _apagar_cliente(self._cliente)


def crear_cliente_mqtt(broker: str, puerto: int, client_id: str,
                       will=None, al_conectar=None):
    """Crea y conecta un cliente paho-mqtt v2 (import perezoso).

    Perezoso a propósito: importar `ocr` o correr los tests (que usan un cliente
    falso) nunca necesita paho-mqtt. Lanza un error claro si falta o no conecta.

    `will`: (topic, carga) opcional — Last Will (ADR-022): el BROKER publica
    ese payload (retained, QoS 1) si el cliente muere sin DISCONNECT. Un
    disconnect limpio NO lo dispara (cerrar() ya publicó el offline explícito:
    cinturón y tirantes). paho re-manda el will en CADA reconexión.
    `al_conectar`: callback on_connect opcional (firma VERSION2 de 5 args).

    El ORDEN importa: will y callbacks ANTES de connect (el will viaja en el
    paquete CONNECT; un callback asignado después del connect correría carrera
    con el primer CONNACK), y loop_start al final.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError as e:
        raise RuntimeError(
            "Falta paho-mqtt para publicar por MQTT. Instala: pip install paho-mqtt "
            "(o usa --solo-consola para probar sin broker)."
        ) from e

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if will is not None:
        topic_will, carga_will = will
        cliente.will_set(topic_will, carga_will, qos=1, retain=True)
    if al_conectar is not None:
        cliente.on_connect = al_conectar
    cliente.on_disconnect = _al_desconectar
    # El backoff por defecto de paho llega a 120 s; acotado como en la ingesta
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    cliente.connect(broker, puerto, keepalive=KEEPALIVE_S)
    cliente.loop_start()
    return cliente


def _apagar_cliente(cliente) -> None:
    """loop_stop + disconnect si el cliente los expone (el falso no).

    on_connect se DESARMA primero (ADR-022): durante la ventana del sleep el
    hilo de red sigue vivo, y una reconexión ahí re-publicaría `online`
    retenido para una cama APAGADA — y el disconnect limpio posterior no
    dispara el will que lo corrija. Hoy paho lo evita de rebote (su
    min_delay de reconexión, 1 s, es mayor que la ventana de 0.3 s); el
    desarme lo vuelve estructural. Si esta ventana crece, mantener
    min_delay de reconnect_delay_set POR ENCIMA de ella.
    """
    if hasattr(cliente, "on_connect"):
        cliente.on_connect = None
    time.sleep(0.3)  # deja salir el mensaje offline (QoS 1) antes de cortar
    for metodo in ("loop_stop", "disconnect"):
        fn = getattr(cliente, metodo, None)
        if callable(fn):
            fn()
