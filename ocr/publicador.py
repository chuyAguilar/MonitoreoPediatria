"""Publicador MQTT del contrato: transporta lo que el lector ya validó.

Replica el patrón del simulador (paho-mqtt v2, QoS 1, retained, ciclo
online/offline) para que `ocr/` quede autocontenido y se despliegue solo en la
Jetson, sin depender de `simulador/` (que vive en otra máquina). Ver el brief
§5 de la iteración 4.

El publicador es SOLO transporte: publica exactamente el mensaje que
`ocr.lector.leer_imagen` devolvió, `null` incluidos. No reinterpreta ni valida
signos — las salvaguardas del OCR ya mandaron aguas arriba.

El cliente MQTT se INYECTA (no lo crea la clase), para poder probar sin broker
con un cliente falso. La CLI usa `crear_cliente_mqtt()` para el cliente real.
"""

import json

from ocr.tiempo import ahora_iso

TOPIC_VITALES = "monitoreo/vitales/{cama_id}"
TOPIC_ESTADO = "monitoreo/estado/{cama_id}"


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
        carga = json.dumps({
            "cama_id": self._cama_id,
            "device_id": self._device_id,
            "estado": estado,
            "ts": ahora_iso(),
        }, ensure_ascii=False)
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


def crear_cliente_mqtt(broker: str, puerto: int, client_id: str):
    """Crea y conecta un cliente paho-mqtt v2 (import perezoso).

    Perezoso a propósito: importar `ocr` o correr los tests (que usan un cliente
    falso) nunca necesita paho-mqtt. Lanza un error claro si falta o no conecta.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError as e:
        raise RuntimeError(
            "Falta paho-mqtt para publicar por MQTT. Instala: pip install paho-mqtt "
            "(o usa --solo-consola para probar sin broker)."
        ) from e

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    cliente.connect(broker, puerto, keepalive=60)
    cliente.loop_start()
    return cliente


def _apagar_cliente(cliente) -> None:
    """loop_stop + disconnect si el cliente los expone (el falso no)."""
    import time
    time.sleep(0.3)  # deja salir el mensaje offline (QoS 1) antes de cortar
    for metodo in ("loop_stop", "disconnect"):
        fn = getattr(cliente, metodo, None)
        if callable(fn):
            fn()
