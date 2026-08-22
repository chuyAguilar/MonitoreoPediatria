"""Almacén SQLite del histórico de vitales (ADR-021).

Esquema ancho (una fila por mensaje, mapea 1:1 al contrato) + `raw` BLOB con
los bytes EXACTOS del payload como red de seguridad: nada se pierde aunque el
esquema evolucione, y la fidelidad es real incluso para basura binaria (un
TEXT con errors='replace' sería lossy justo cuando más importa).

Columnas de auditoría por fila:
- `topic`: de qué topic llegó (un payload puede afirmar otra cama_id: ambos
  rastros quedan).
- `retenido` (0/1): re-entrega retained del broker en cada (re)suscripción —
  arranques Y reconexiones — no una lectura fresca.
- `malformado` (0/1): algún campo PRESENTE falló la forma (tipo inesperado,
  int fuera de 64 bits, float no finito) y fue a NULL. Distingue el NULL-por-
  basura del null-del-OCR, que es semántica clínica real ("no pudo leer").
  Guía de lectura: tendencias/conteos con `retenido=0 AND malformado=0`.

La tabla `eventos_ingesta` registra los huecos del PROPIO servicio (arranques,
descartes por tope): los huecos de una caja negra deben explicarse EN el
registro, no en un journald que rota.

Amable con la eMMC del servidor: WAL + synchronous=NORMAL (el commit escribe
al -wal SIN fsync; el fsync ocurre en el checkpoint, ~1000 páginas). Ventana
ante corte de energía = commits desde el último checkpoint; ante crash del
proceso, WAL no pierde nada commiteado. `synchronous` y `busy_timeout` son
POR CONEXIÓN (se fijan en cada connect); `journal_mode=WAL` sí persiste en el
archivo. Una sola conexión, dueña: solo el hilo que la creó escribe.
"""

import os
import sqlite3

VERSION_ESQUEMA = 1

# -wal acotado tras cada checkpoint (eMMC): 4 MB
_LIMITE_JOURNAL_BYTES = 4 * 1024 * 1024

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS vitales (
  id INTEGER PRIMARY KEY,
  contrato TEXT, cama_id TEXT, device_id TEXT, origen TEXT,
  ts TEXT, recibido_en TEXT, topic TEXT, retenido INTEGER, malformado INTEGER,
  fc INTEGER, fc_conf REAL, spo2 INTEGER, spo2_conf REAL,
  fp INTEGER, fp_conf REAL, fr INTEGER, fr_conf REAL,
  temp REAL, temp_conf REAL,
  pni_sis INTEGER, pni_dia INTEGER, pni_media INTEGER, pni_conf REAL, pni_ts TEXT,
  raw BLOB
);
CREATE INDEX IF NOT EXISTS idx_vitales_cama_ts ON vitales(cama_id, ts);

CREATE TABLE IF NOT EXISTS estado (
  id INTEGER PRIMARY KEY,
  cama_id TEXT, device_id TEXT, estado TEXT,
  ts TEXT, recibido_en TEXT, topic TEXT, retenido INTEGER, malformado INTEGER,
  raw BLOB
);
CREATE INDEX IF NOT EXISTS idx_estado_cama_ts ON estado(cama_id, ts);

CREATE TABLE IF NOT EXISTS eventos_ingesta (
  id INTEGER PRIMARY KEY,
  ts TEXT, evento TEXT, detalle TEXT
);
"""

_INSERT_VITALES = (
    "INSERT INTO vitales (contrato, cama_id, device_id, origen, ts, recibido_en,"
    " topic, retenido, malformado, fc, fc_conf, spo2, spo2_conf, fp, fp_conf,"
    " fr, fr_conf, temp, temp_conf, pni_sis, pni_dia, pni_media, pni_conf,"
    " pni_ts, raw) VALUES (" + ",".join("?" * 25) + ")"
)
_INSERT_ESTADO = (
    "INSERT INTO estado (cama_id, device_id, estado, ts, recibido_en, topic,"
    " retenido, malformado, raw) VALUES (" + ",".join("?" * 9) + ")"
)
_INSERT_EVENTO = "INSERT INTO eventos_ingesta (ts, evento, detalle) VALUES (?,?,?)"


class AlmacenVitales:
    """Dueña única de la conexión SQLite. Crea el esquema idempotentemente."""

    def __init__(self, ruta):
        self._ruta = str(ruta)
        if self._ruta != ":memory:":
            directorio = os.path.dirname(os.path.abspath(self._ruta))
            os.makedirs(directorio, exist_ok=True)
        self._conn = sqlite3.connect(self._ruta)
        self._preparar()

    def _preparar(self):
        c = self._conn
        # Fail-hard ANTES del DDL: apuntar este código a una BD de un esquema
        # futuro (rollback de software, INGESTA_BD equivocada) escribiría
        # filas v1 en una BD v2 en silencio — los CREATE IF NOT EXISTS no
        # protestan. Una futura v2 migra AQUÍ.
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, VERSION_ESQUEMA):
            c.close()
            raise RuntimeError(
                f"La BD {self._ruta!r} tiene esquema v{version}; este código "
                f"solo entiende v{VERSION_ESQUEMA}. ¿Rollback de software o "
                f"ruta equivocada?"
            )
        # WAL puede NO tomar efecto sin lanzar (filesystem sin shared memory):
        # seguir con journal DELETE rompería las promesas de durabilidad y de
        # patrón de escritura del ADR-021 en silencio — fail-hard.
        modo = c.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if self._ruta != ":memory:" and modo != "wal":
            c.close()
            raise RuntimeError(
                f"SQLite no aceptó WAL en {self._ruta!r} (journal_mode="
                f"{modo!r}): ¿filesystem de red o sin memoria compartida?"
            )
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute(f"PRAGMA journal_size_limit={_LIMITE_JOURNAL_BYTES}")
        c.executescript(_ESQUEMA)
        if c.execute("PRAGMA user_version").fetchone()[0] == 0:
            c.execute(f"PRAGMA user_version={VERSION_ESQUEMA}")
        c.commit()

    @property
    def ruta(self) -> str:
        return self._ruta

    @property
    def journal_mode(self) -> str:
        """'wal' en archivo; una BD :memory: reporta 'memory' (no aplica WAL)."""
        return self._conn.execute("PRAGMA journal_mode").fetchone()[0]

    @property
    def version_esquema(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def insertar_lote(self, filas_vitales, filas_estado) -> None:
        """executemany + UN commit. Lanza si SQLite falla: el servicio decide
        (aislar la fila venenosa o conservar la cola y reintentar).

        Rollback defensivo primero: si una señal interrumpió un lote anterior
        entre el executemany y el commit, la transacción quedó abierta CON
        esas filas dentro — reintentar encima las duplicaría en el histórico.
        """
        if self._conn.in_transaction:
            self._conn.rollback()
        if filas_vitales:
            self._conn.executemany(_INSERT_VITALES, filas_vitales)
        if filas_estado:
            self._conn.executemany(_INSERT_ESTADO, filas_estado)
        self._conn.commit()

    def insertar_fila(self, es_vitales: bool, fila) -> None:
        """Un insert SIN commit (para aislar fila a fila un lote envenenado)."""
        sql = _INSERT_VITALES if es_vitales else _INSERT_ESTADO
        self._conn.execute(sql, fila)

    def confirmar(self) -> None:
        self._conn.commit()

    def deshacer(self) -> None:
        self._conn.rollback()

    def registrar_evento(self, ts: str, evento: str, detalle: str = "") -> None:
        """Evento del propio servicio (arranque, descartes). Commit propio."""
        self._conn.execute(_INSERT_EVENTO, (ts, evento, detalle))
        self._conn.commit()

    def contar(self, tabla: str) -> int:
        if tabla not in ("vitales", "estado", "eventos_ingesta"):
            raise ValueError(f"Tabla desconocida: {tabla!r}")
        return self._conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]

    def cerrar(self) -> None:
        """Idempotente. Commit final defensivo antes de cerrar."""
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.commit()
            finally:
                conn.close()
