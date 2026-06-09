"""Generador de signos vitales neonatales simulados.

Produce valores que varían suavemente en el tiempo (no fijos), dentro de rangos
neonatales realistas, y los empaqueta en el formato del contrato de datos
(ver docs/ito2/CONTRATO_DATOS.md).

Cada cama usa una instancia con baselines ligeramente distintos, para que se
vean diferentes entre sí.
"""

import random
from datetime import datetime, timezone


def ahora_iso() -> str:
    """Fecha/hora UTC en formato ISO-8601 con sufijo Z."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class GeneradorSignos:
    """Simula la evolución de los signos vitales de una cama."""

    def __init__(self, semilla: int | None = None, intervalo_pni_s: float = 30.0):
        self.rng = random.Random(semilla)

        # Baselines (objetivo de reversión a la media), distintos por cama
        self.base_fc = self.rng.uniform(130, 150)
        self.base_spo2 = self.rng.uniform(96, 99)
        self.base_fr = self.rng.uniform(42, 55)
        self.base_temp = self.rng.uniform(36.6, 37.2)

        # Valores actuales
        self.fc = self.base_fc
        self.spo2 = self.base_spo2
        self.fr = self.base_fr
        self.temp = self.base_temp

        # Presión no invasiva (intermitente)
        self.intervalo_pni = intervalo_pni_s
        self._t_desde_pni = intervalo_pni_s  # fuerza una medición al inicio
        self.pni_sis = self.rng.uniform(60, 72)
        self.pni_dia = self.rng.uniform(35, 45)
        self.pni_ts = ahora_iso()

    def _paso_valor(self, valor, base, k, ruido, lo, hi):
        """Random walk con reversión a la media, acotado a [lo, hi]."""
        valor += k * (base - valor) + self.rng.uniform(-ruido, ruido)
        return max(lo, min(hi, valor))

    def paso(self, dt: float) -> None:
        """Avanza la simulación dt segundos."""
        self.fc = self._paso_valor(self.fc, self.base_fc, 0.05, 1.5, 110, 170)
        self.spo2 = self._paso_valor(self.spo2, self.base_spo2, 0.08, 0.4, 88, 100)
        self.fr = self._paso_valor(self.fr, self.base_fr, 0.06, 1.2, 30, 70)
        self.temp = self._paso_valor(self.temp, self.base_temp, 0.02, 0.03, 36.0, 38.0)

        # NIBP: nueva medición cada intervalo_pni segundos
        self._t_desde_pni += dt
        if self._t_desde_pni >= self.intervalo_pni:
            self._t_desde_pni = 0.0
            self.pni_sis = self.rng.uniform(58, 74)
            self.pni_dia = self.rng.uniform(34, 46)
            self.pni_ts = ahora_iso()

    def construir_mensaje(self, cama_id: str, device_id: str, origen: str = "simulador") -> dict:
        """Devuelve el mensaje de numéricos según el contrato 1.0."""
        fp = self.fc + self.rng.uniform(-2, 2)  # frecuencia de pulso ~ FC
        sis = round(self.pni_sis)
        dia = round(self.pni_dia)
        media = round(dia + (sis - dia) / 3)  # presión arterial media

        return {
            "contrato": "1.0",
            "cama_id": cama_id,
            "device_id": device_id,
            "ts": ahora_iso(),
            "origen": origen,
            "signos": {
                "fc": {"valor": round(self.fc), "unidad": "lpm"},
                "spo2": {"valor": round(self.spo2), "unidad": "%"},
                "fp": {"valor": round(fp), "unidad": "lpm"},
                "fr": {"valor": round(self.fr), "unidad": "rpm"},
                "temp": {"valor": round(self.temp, 1), "unidad": "C"},
                "pni": {
                    "sis": sis,
                    "dia": dia,
                    "media": media,
                    "unidad": "mmHg",
                    "ts": self.pni_ts,
                },
            },
        }
