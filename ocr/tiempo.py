"""Marca de tiempo del contrato: UTC ISO-8601 con sufijo Z.

Compartida por el lector y el publicador para que el `ts` del contrato tenga el
mismo formato en un solo sitio (mismo formato que produce el simulador).
"""

from datetime import datetime, timezone


def ahora_iso() -> str:
    """Fecha/hora UTC actual en ISO-8601 con sufijo Z (sin microsegundos)."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
