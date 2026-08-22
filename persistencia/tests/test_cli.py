"""Disciplina del CLI: wiring, envs, arranque estricto, --solo-esquema."""

import pytest

from persistencia import ingerir, ingestor

from .conftest import ClienteFalso


class _ServicioStub:
    instancias = []

    def __init__(self, almacen, lote, intervalo_s):
        self.almacen = almacen
        self.lote = lote
        self.intervalo_s = intervalo_s
        self.corridas = 0
        self.vaciado_final = 0
        _ServicioStub.instancias.append(self)

    def correr(self):
        self.corridas += 1

    def vaciar_final(self):
        self.vaciado_final += 1


@pytest.fixture(autouse=True)
def _limpiar():
    _ServicioStub.instancias = []
    yield
    _ServicioStub.instancias = []


def _con_stubs(monkeypatch):
    monkeypatch.setattr(ingestor, "ServicioIngesta", _ServicioStub)
    creados = []

    def crear(broker, puerto, servicio, client_id=ingestor.CLIENT_ID):
        creados.append((broker, puerto, servicio))
        return ClienteFalso()

    monkeypatch.setattr(ingestor, "crear_cliente_suscriptor", crear)
    return creados


def test_wiring_positivo_y_cierre_ordenado(monkeypatch, tmp_path):
    creados = _con_stubs(monkeypatch)
    codigo = ingerir.main([
        "--broker", "10.0.0.5", "--puerto-broker", "2883",
        "--bd", str(tmp_path / "v.db"), "--lote", "7", "--intervalo", "2.5",
    ])
    assert codigo == 0
    (stub,) = _ServicioStub.instancias
    assert (stub.lote, stub.intervalo_s) == (7, 2.5)
    assert creados[0][:2] == ("10.0.0.5", 2883)
    assert stub.corridas == 1
    assert stub.vaciado_final == 1, "el cierre siempre vacía el pendiente"


def test_envs_dentro_de_main(monkeypatch, tmp_path):
    _con_stubs(monkeypatch)
    monkeypatch.setenv("INGESTA_BROKER", "servidor-x")
    monkeypatch.setenv("INGESTA_PUERTO", "3883")
    monkeypatch.setenv("INGESTA_BD", str(tmp_path / "env.db"))
    monkeypatch.setenv("INGESTA_LOTE", "42")
    monkeypatch.setenv("INGESTA_INTERVALO", "9")
    assert ingerir.main([]) == 0
    (stub,) = _ServicioStub.instancias
    assert (stub.lote, stub.intervalo_s) == (42, 9.0)
    assert stub.almacen.ruta == str(tmp_path / "env.db")


def test_lote_e_intervalo_invalidos_exit_2(capsys):
    for argv in (["--lote", "0"], ["--lote", "abc"],
                 ["--intervalo", "0"], ["--intervalo", "nan"]):
        with pytest.raises(SystemExit):
            ingerir.main(argv)
        err = capsys.readouterr().err
        assert "--lote" in err or "--intervalo" in err


def test_env_con_basura_tambien_exit_2(monkeypatch, capsys):
    # argparse aplica type= a los defaults string: el env pasa por el MISMO
    # validador accionable que el flag.
    monkeypatch.setenv("INGESTA_LOTE", "-5")
    with pytest.raises(SystemExit):
        ingerir.main([])
    assert "--lote" in capsys.readouterr().err


def test_solo_esquema_crea_y_sale(tmp_path, capsys):
    ruta = tmp_path / "nueva" / "v.db"
    assert ingerir.main(["--bd", str(ruta), "--solo-esquema"]) == 0
    assert ruta.exists()
    assert "esquema listo" in capsys.readouterr().out


def test_bd_no_creable_exit_1(tmp_path, capsys):
    bloqueo = tmp_path / "archivo"
    bloqueo.write_text("no soy un directorio")
    codigo = ingerir.main(["--bd", str(bloqueo / "v.db"), "--solo-esquema"])
    assert codigo == 1
    assert "ERROR" in capsys.readouterr().out


def test_broker_caido_exit_1_accionable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ingestor, "ServicioIngesta", _ServicioStub)

    def revienta(*a, **k):
        raise OSError("Connection refused")

    monkeypatch.setattr(ingestor, "crear_cliente_suscriptor", revienta)
    codigo = ingerir.main(["--bd", str(tmp_path / "v.db")])
    assert codigo == 1
    salida = capsys.readouterr().out
    assert "ERROR" in salida and "Mosquitto" in salida


def test_orden_del_cierre_loop_stop_vaciado_cerrar(monkeypatch, tmp_path):
    # Si el vaciado final corriera ANTES de parar el cliente, el hilo de red
    # seguiría encolando durante el flush y esos mensajes morirían con el
    # proceso — perforando el histórico justo en cada deploy.
    bitacora = []

    class _ServicioBitacora(_ServicioStub):
        def vaciar_final(self):
            bitacora.append("vaciar_final")
            super().vaciar_final()

    class _ClienteBitacora(ClienteFalso):
        def loop_stop(self):
            bitacora.append("loop_stop")
            super().loop_stop()

        def disconnect(self):
            bitacora.append("disconnect")
            super().disconnect()

    class _AlmacenBitacora:
        ruta = "stub"
        journal_mode = "wal"
        version_esquema = 1

        def __init__(self, ruta):
            pass

        def cerrar(self):
            bitacora.append("cerrar")

    monkeypatch.setattr(ingerir, "AlmacenVitales", _AlmacenBitacora)
    monkeypatch.setattr(ingestor, "ServicioIngesta", _ServicioBitacora)
    monkeypatch.setattr(ingestor, "crear_cliente_suscriptor",
                        lambda *a, **k: _ClienteBitacora())
    assert ingerir.main(["--bd", str(tmp_path / "v.db")]) == 0
    assert bitacora == ["loop_stop", "disconnect", "vaciar_final", "cerrar"]


def test_connack_fatal_exit_1(monkeypatch, tmp_path, capsys):
    class _ServicioRechazado(_ServicioStub):
        def correr(self):
            raise RuntimeError("el broker rechaza la conexión (CONNACK)")

    monkeypatch.setattr(ingestor, "ServicioIngesta", _ServicioRechazado)
    monkeypatch.setattr(ingestor, "crear_cliente_suscriptor",
                        lambda *a, **k: ClienteFalso())
    codigo = ingerir.main(["--bd", str(tmp_path / "v.db")])
    assert codigo == 1
    assert "CONNACK" in capsys.readouterr().out
