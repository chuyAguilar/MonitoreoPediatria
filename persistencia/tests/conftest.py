"""Fixtures de la ingesta: mensajes del contrato, cliente MQTT falso, reloj.

Ningún test usa broker, hilos de paho ni disco (salvo las aserciones de WAL,
que necesitan archivo: :memory: reporta journal_mode='memory').
"""

import json

import pytest

from persistencia.almacen import AlmacenVitales

# Mensaje 1.1 literal (réplica del contrato que emite ocr/, con null y PNI)
MENSAJE_11 = {
    "contrato": "1.1",
    "cama_id": "cama-09",
    "device_id": "jetson-01",
    "ts": "2026-08-22T10:00:00+00:00",
    "origen": "ocr",
    "signos": {
        "fc": {"valor": 142, "unidad": "lpm", "confianza": 0.98},
        "spo2": {"valor": 97, "unidad": "%", "confianza": 0.95},
        "fp": {"valor": None, "unidad": "lpm", "confianza": 0.0},
        "fr": {"valor": 44, "unidad": "rpm", "confianza": 0.91},
        "temp": {"valor": 36.8, "unidad": "C", "confianza": 0.97},
        "pni": {
            "sis": 68, "dia": 38, "media": 48, "unidad": "mmHg",
            "ts": "2026-08-22T09:58:30+00:00", "confianza": 0.9,
        },
    },
}

# Mensaje 1.0 literal (forma del simulador: signos SIN confianza)
MENSAJE_10 = {
    "contrato": "1.0",
    "cama_id": "cama-03",
    "device_id": "edge-01",
    "ts": "2026-08-22T10:00:01+00:00",
    "origen": "simulador",
    "signos": {
        "fc": {"valor": 138, "unidad": "lpm"},
        "spo2": {"valor": 96, "unidad": "%"},
        "fp": {"valor": 137, "unidad": "lpm"},
        "fr": {"valor": 52, "unidad": "rpm"},
        "temp": {"valor": 36.9, "unidad": "C"},
        "pni": {"sis": 66, "dia": 40, "media": 49, "unidad": "mmHg",
                "ts": "2026-08-22T09:59:40+00:00"},
    },
}

MENSAJE_ESTADO = {
    "cama_id": "cama-09",
    "device_id": "jetson-01",
    "estado": "online",
    "ts": "2026-08-22T10:00:00+00:00",
}


def carga(mensaje) -> bytes:
    return json.dumps(mensaje, ensure_ascii=False).encode("utf-8")


class RelojFalso:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avanzar(self, s):
        self.t += s


class ClienteFalso:
    """Registra subscribe/loop_stop/disconnect; sirve para al_conectar."""

    def __init__(self):
        self.suscripciones = []
        self.parado = False
        self.desconectado = False

    def subscribe(self, topics):
        self.suscripciones.append(topics)
        return (0, 1)  # (MQTT_ERR_SUCCESS, mid) — lo que devuelve paho

    def loop_stop(self):
        self.parado = True

    def disconnect(self):
        self.desconectado = True


class MensajeFalso:
    """Lo mínimo de paho MQTTMessage que usa al_recibir."""

    def __init__(self, topic, payload, retain=False):
        self.topic = topic
        self.payload = payload
        self.retain = retain


class CodigoConexion:
    def __init__(self, es_fallo):
        self.is_failure = es_fallo

    def __str__(self):
        return "Not authorized" if self.is_failure else "Success"


@pytest.fixture()
def almacen():
    a = AlmacenVitales(":memory:")
    yield a
    a.cerrar()
