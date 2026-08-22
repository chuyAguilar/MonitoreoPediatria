"""Almacén SQLite: esquema idempotente, WAL, lotes, eventos, veneno aislable."""

import sqlite3

import pytest

from persistencia.almacen import VERSION_ESQUEMA, AlmacenVitales
from persistencia.ingestor import fila_de_estado, fila_de_vitales

from .conftest import MENSAJE_11, MENSAJE_ESTADO, carga

AHORA = "2026-08-22T10:00:02+00:00"


def _fila_vitales():
    return fila_de_vitales("monitoreo/vitales/cama-09", carga(MENSAJE_11),
                           False, AHORA)


def _fila_estado():
    return fila_de_estado("monitoreo/estado/cama-09", carga(MENSAJE_ESTADO),
                          False, AHORA)


def test_esquema_idempotente_y_version(tmp_path):
    ruta = tmp_path / "vitales.db"
    a = AlmacenVitales(ruta)
    a.cerrar()
    b = AlmacenVitales(ruta)  # segunda creación sobre la misma BD: no truena
    assert b.version_esquema == VERSION_ESQUEMA
    b.cerrar()


def test_wal_activo_en_archivo(tmp_path):
    # La aserción de WAL exige archivo: una BD :memory: reporta 'memory'.
    a = AlmacenVitales(tmp_path / "vitales.db")
    assert a.journal_mode == "wal"
    assert a._conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    a.cerrar()


def test_crea_directorio_de_la_bd(tmp_path):
    ruta = tmp_path / "sub" / "dir" / "vitales.db"
    a = AlmacenVitales(ruta)
    a.cerrar()
    assert ruta.exists()


def test_insertar_lote_ambas_tablas(almacen):
    almacen.insertar_lote([_fila_vitales()] * 3, [_fila_estado()] * 2)
    assert almacen.contar("vitales") == 3
    assert almacen.contar("estado") == 2
    fila = almacen._conn.execute(
        "SELECT cama_id, fc, fp, pni_sis, pni_ts, retenido, malformado, raw "
        "FROM vitales LIMIT 1").fetchone()
    assert fila == ("cama-09", 142, None, 68,
                    "2026-08-22T09:58:30+00:00", 0, 0, carga(MENSAJE_11))


def test_raw_es_blob(almacen):
    almacen.insertar_lote([_fila_vitales()], [])
    tipo = almacen._conn.execute("SELECT typeof(raw) FROM vitales").fetchone()[0]
    assert tipo == "blob"


def test_registrar_evento(almacen):
    almacen.registrar_evento(AHORA, "arranque", "lote=100")
    assert almacen.contar("eventos_ingesta") == 1


def test_fila_venenosa_aislable(almacen):
    # Una tupla con un dict no-bindeable lanza en el lote; fila a fila el
    # resto se persiste (el patrón que usa ServicioIngesta._aislar_veneno).
    buena = _fila_vitales()
    venenosa = buena._replace(ts={"a": 1})  # no-bindeable a propósito
    with pytest.raises((sqlite3.InterfaceError, sqlite3.ProgrammingError)):
        almacen.insertar_lote([buena, venenosa], [])
    almacen.deshacer()
    almacen.insertar_fila(True, buena)
    with pytest.raises((sqlite3.InterfaceError, sqlite3.ProgrammingError)):
        almacen.insertar_fila(True, venenosa)
    almacen.confirmar()
    assert almacen.contar("vitales") == 1


def test_insertar_lote_deshace_transaccion_colgada(almacen):
    # Un lote anterior interrumpido entre executemany y commit deja la
    # transacción abierta CON sus filas: sin el rollback defensivo, el
    # reintento las duplicaría.
    almacen.insertar_fila(True, _fila_vitales())  # transacción abierta
    assert almacen._conn.in_transaction
    almacen.insertar_lote([_fila_vitales()], [])
    assert almacen.contar("vitales") == 1, "solo el lote del reintento"


def test_bd_de_esquema_futuro_falla_fuerte(tmp_path):
    ruta = tmp_path / "v.db"
    a = AlmacenVitales(ruta)
    a._conn.execute("PRAGMA user_version=99")
    a._conn.commit()
    a.cerrar()
    with pytest.raises(RuntimeError, match="v99"):
        AlmacenVitales(ruta)


def test_cerrar_idempotente(almacen):
    almacen.cerrar()
    almacen.cerrar()
