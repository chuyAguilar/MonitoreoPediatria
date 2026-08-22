"""ServicioIngesta: cola, lotes, venenos, tope, re-suscripción, cierre."""

import threading

from persistencia import ingestor
from persistencia.ingestor import ServicioIngesta

from .conftest import (
    MENSAJE_11,
    MENSAJE_ESTADO,
    ClienteFalso,
    CodigoConexion,
    MensajeFalso,
    RelojFalso,
    carga,
)

TOPIC = "monitoreo/vitales/cama-09"


def _servicio(almacen, **kwargs):
    return ServicioIngesta(almacen, reloj=RelojFalso(),
                           ahora=lambda: "2026-08-22T10:00:02+00:00", **kwargs)


def _recibir(servicio, mensaje=None, topic=TOPIC, retain=False, payload=None):
    servicio.al_recibir(None, None, MensajeFalso(
        topic, payload if payload is not None else carga(mensaje or MENSAJE_11),
        retain))


def test_encola_y_vacia(almacen):
    s = _servicio(almacen)
    _recibir(s)
    _recibir(s, mensaje=MENSAJE_ESTADO, topic="monitoreo/estado/cama-09")
    s._vaciar()
    assert almacen.contar("vitales") == 1
    assert almacen.contar("estado") == 1
    assert len(s._pendientes) == 0


def test_lote_n_dispara_el_evento(almacen):
    s = _servicio(almacen, lote=3)
    for _ in range(2):
        _recibir(s)
    assert not s._hay_trabajo.is_set(), "por debajo de N no despierta"
    _recibir(s)
    assert s._hay_trabajo.is_set(), "al llegar a N despierta al escritor"


def test_basura_se_salta_y_el_servicio_sigue(almacen, capsys):
    s = _servicio(almacen)
    _recibir(s, payload=b"esto no es json")
    _recibir(s, payload=b"[1,2]")
    s._vaciar()
    assert almacen.contar("vitales") == 0
    salida = capsys.readouterr().out
    assert "descartado" in salida
    # regla de privacidad: nunca el payload completo, tope de 80 caracteres
    assert "esto no es json" in salida  # cabe en 80


def test_payload_sobre_tope_se_salta_sin_volcarlo(almacen, capsys):
    s = _servicio(almacen)
    gigante = b"x" * (ingestor.TOPE_PAYLOAD_BYTES + 1)
    _recibir(s, payload=gigante)
    s._vaciar()
    assert almacen.contar("vitales") == 0
    salida = capsys.readouterr().out
    assert "supera el tope" in salida
    assert "xxxxxxxxxx" not in salida, "el contenido no se vuelca al log"


def test_excepcion_en_el_encolado_no_mata_el_hilo_de_red(almacen, capsys):
    # La garantía estructural: aunque falle ALGO MÁS que el parseo (aquí el
    # encolado), al_recibir jamás deja subir la excepción — en paho v2 mataría
    # el hilo de red sin reconexión con el servicio "active" para systemd.
    s = _servicio(almacen)
    s._encolar = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    _recibir(s)  # no debe propagar
    assert "error procesando" in capsys.readouterr().out


def test_cama_id_payload_manda_y_se_avisa_si_difiere(almacen, capsys):
    s = _servicio(almacen)
    _recibir(s, topic="monitoreo/vitales/cama-01")  # payload dice cama-09
    s._vaciar()
    fila = almacen._conn.execute(
        "SELECT cama_id, topic FROM vitales").fetchone()
    assert fila == ("cama-09", "monitoreo/vitales/cama-01")
    assert "AVISO" in capsys.readouterr().out


def test_retirar_solo_tras_commit(almacen):
    # Si el commit no ocurre (señal a mitad del vaciado), la cola queda
    # intacta: nada se pierde.
    s = _servicio(almacen)
    _recibir(s)
    original = almacen.insertar_lote

    def interrumpe(*a):
        raise KeyboardInterrupt

    almacen.insertar_lote = interrumpe
    try:
        s._vaciar()
        raise AssertionError("debía propagar KeyboardInterrupt")
    except KeyboardInterrupt:
        pass
    assert len(s._pendientes) == 1, "la cola conserva lo no commiteado"
    almacen.insertar_lote = original
    s.vaciar_final()
    assert almacen.contar("vitales") == 1


def test_vaciar_final_reintenta_ante_segunda_senal(almacen):
    s = _servicio(almacen)
    _recibir(s)
    original = almacen.insertar_lote
    golpes = {"n": 0}

    def primero_interrumpe(*a):
        golpes["n"] += 1
        if golpes["n"] == 1:
            raise KeyboardInterrupt
        return original(*a)

    almacen.insertar_lote = primero_interrumpe
    s.vaciar_final()  # segunda señal simulada: reintenta y persiste
    assert almacen.contar("vitales") == 1


def test_lote_envenenado_se_aisla_y_el_resto_persiste(almacen, capsys):
    s = _servicio(almacen)
    _recibir(s)
    buena = s._pendientes[0][1]
    s._pendientes.append((True, buena._replace(ts={"a": 1})))  # veneno
    _recibir(s)
    s._vaciar()
    assert almacen.contar("vitales") == 2, "las buenas se persisten"
    assert len(s._pendientes) == 0, "el veneno se descartó, no gira eterno"
    assert "fila descartada" in capsys.readouterr().out


def test_sqlite_caida_conserva_la_cola_y_reintenta(almacen, capsys):
    s = _servicio(almacen)
    _recibir(s)
    original = almacen.insertar_lote
    almacen.insertar_lote = lambda *a: (_ for _ in ()).throw(
        RuntimeError("disco lleno"))
    fallo_fila = almacen.insertar_fila
    almacen.insertar_fila = lambda *a: (_ for _ in ()).throw(
        RuntimeError("disco lleno"))
    s._vaciar()  # no lanza: conserva la cola y agenda el backoff
    assert len(s._pendientes) == 1
    almacen.insertar_lote = original
    almacen.insertar_fila = fallo_fila
    s._vaciar()  # dentro del backoff: NO reintenta por mensaje (eMMC)
    assert almacen.contar("vitales") == 0
    s._reloj.avanzar(6)  # supera el intervalo -> reintenta y persiste
    s._vaciar()
    assert almacen.contar("vitales") == 1


def test_tope_descarta_lo_viejo_y_lo_registra(almacen, monkeypatch, capsys):
    monkeypatch.setattr(ingestor, "MAX_PENDIENTES", 3)
    s = _servicio(almacen)
    for _ in range(5):
        _recibir(s)
    assert len(s._pendientes) == 3
    s._vaciar()
    assert almacen.contar("vitales") == 3
    eventos = almacen._conn.execute(
        "SELECT evento, detalle FROM eventos_ingesta").fetchall()
    assert any(e == "descarte" and "2 mensajes" in d for e, d in eventos), \
        "el hueco queda explicado EN el histórico"


def test_al_conectar_resuscribe_en_cada_reconexion():
    s = ServicioIngesta.__new__(ServicioIngesta)  # solo el wiring MQTT
    s._connack_rechazados = 0
    s._conexion_rechazada = None
    s._hay_trabajo = threading.Event()
    cliente = ClienteFalso()
    for _ in range(2):  # conexión inicial + reconexión
        s.al_conectar(cliente, None, None, CodigoConexion(es_fallo=False))
    assert cliente.suscripciones == [
        [("monitoreo/vitales/+", 1), ("monitoreo/estado/+", 1)],
        [("monitoreo/vitales/+", 1), ("monitoreo/estado/+", 1)],
    ], "re-suscripción con QoS 1 en CADA on_connect"


def test_connack_rechazado_no_suscribe_y_repetido_es_fatal(almacen):
    s = _servicio(almacen)
    cliente = ClienteFalso()
    for _ in range(ingestor.MAX_CONNACK_RECHAZADOS):
        s.al_conectar(cliente, None, None, CodigoConexion(es_fallo=True))
    assert cliente.suscripciones == [], "jamás suscribir tras CONNACK fallido"
    assert s._conexion_rechazada is not None
    assert s._hay_trabajo.is_set(), "despierta al hilo principal para salir"


def test_senal_entre_executemany_y_commit_no_duplica(almacen):
    # La ventana dual del retirar-tras-commit: la señal cae DESPUÉS del
    # executemany y ANTES del commit — la transacción abierta ya contiene las
    # filas; sin el rollback del except, el vaciado final las DUPLICARÍA.
    from persistencia.almacen import _INSERT_VITALES

    s = _servicio(almacen)
    _recibir(s)
    original = almacen.insertar_lote

    def executemany_sin_commit(vitales, estados):
        # replica insertar_lote hasta justo ANTES del commit y "recibe" ahí
        # la señal: transacción abierta CON las filas dentro
        almacen._conn.executemany(_INSERT_VITALES, vitales)
        assert almacen._conn.in_transaction
        raise KeyboardInterrupt

    almacen.insertar_lote = executemany_sin_commit
    try:
        s._vaciar()
        raise AssertionError("debía propagar KeyboardInterrupt")
    except KeyboardInterrupt:
        pass
    assert not almacen._conn.in_transaction, \
        "el except debe deshacer la transacción abierta antes de re-lanzar"
    almacen.insertar_lote = original
    s.vaciar_final()
    assert almacen.contar("vitales") == 1, "una señal jamás duplica filas"


def test_contrato_desconocido_avisa_pero_persiste(almacen, capsys):
    s = _servicio(almacen)
    _recibir(s, mensaje={**MENSAJE_11, "contrato": "2.0"})
    s._vaciar()
    assert almacen.contar("vitales") == 1
    assert "contrato '2.0' desconocido" in capsys.readouterr().out


def test_correr_real_evento_arranque_vaciado_por_T_y_resumen(almacen, capsys):
    # El correr() REAL: evento de arranque, vaciado por T (el timeout del
    # wait) y resumen a los 60 s con reset del contador.
    s = _servicio(almacen)
    reloj = s._reloj

    class EventoGuionizado:
        """wait() avanza el reloj T segundos (simula el timeout) y corta con
        KeyboardInterrupt tras N ticks."""

        def __init__(self, ticks):
            self.ticks = ticks

        def wait(self, timeout=None):
            if self.ticks == 0:
                raise KeyboardInterrupt
            self.ticks -= 1
            reloj.avanzar(timeout)
            return False

        def clear(self):
            pass

    _recibir(s)  # 1 mensaje encolado, por debajo de N=100
    s._hay_trabajo = EventoGuionizado(ticks=13)  # 13 × 5 s = 65 s > 60
    s.correr()
    assert almacen.contar("vitales") == 1, "el vaciado por T escribió sin llegar a N"
    eventos = almacen._conn.execute(
        "SELECT evento FROM eventos_ingesta").fetchall()
    assert ("arranque",) in eventos
    salida = capsys.readouterr().out
    assert "filas escritas en el último minuto" in salida
    assert s._escritas_minuto == 0, "el resumen resetea el contador"


def test_correr_sale_fatal_con_conexion_rechazada(almacen):
    s = _servicio(almacen)

    class EventoQueDespierta:
        def wait(self, timeout=None):
            s._conexion_rechazada = "el broker rechaza la conexión (CONNACK)"
            return True

        def clear(self):
            pass

    s._hay_trabajo = EventoQueDespierta()
    try:
        s.correr()
        raise AssertionError("debía lanzar RuntimeError")
    except RuntimeError as e:
        assert "CONNACK" in str(e)


def test_al_conectar_con_la_aridad_real_de_paho_v2(capsys):
    # paho v2 SIEMPRE pasa 5 argumentos posicionales: si alguien quita el
    # parámetro properties "que no se usa", paho lanza TypeError AL INVOCAR
    # y mata el hilo de red. Este test fija la aridad real.
    s = ServicioIngesta.__new__(ServicioIngesta)
    s._connack_rechazados = 0
    s._conexion_rechazada = None
    s._hay_trabajo = threading.Event()
    cliente = ClienteFalso()

    class Flags:
        session_present = True

    s.al_conectar(cliente, None, Flags(), CodigoConexion(es_fallo=False), None)
    assert len(cliente.suscripciones) == 1
    assert "sesión retomada" in capsys.readouterr().out
    s.al_desconectar(cliente, None, None, CodigoConexion(es_fallo=False), None)
    s.al_suscribir(cliente, None, 1, [CodigoConexion(es_fallo=False)], None)


def test_suback_rechazado_es_fatal(almacen):
    # ACL futura: CONNACK acepta pero el SUBACK deniega -> sin esta guardia el
    # servicio quedaría "conectado" sin ingerir jamás, en silencio.
    s = _servicio(almacen)
    s.al_suscribir(None, None, 7, [CodigoConexion(es_fallo=False),
                                   CodigoConexion(es_fallo=True)], None)
    assert s._conexion_rechazada is not None
    assert "suscripción" in s._conexion_rechazada
    assert s._hay_trabajo.is_set()


def test_connack_reset_del_contador_en_exito(almacen):
    # Rechazos intermitentes repartidos entre reconexiones exitosas jamás
    # deben acumular hasta el fatal.
    s = _servicio(almacen)
    cliente = ClienteFalso()
    for _ in range(ingestor.MAX_CONNACK_RECHAZADOS - 1):
        s.al_conectar(cliente, None, None, CodigoConexion(es_fallo=True), None)
    s.al_conectar(cliente, None, None, CodigoConexion(es_fallo=False), None)
    for _ in range(ingestor.MAX_CONNACK_RECHAZADOS - 1):
        s.al_conectar(cliente, None, None, CodigoConexion(es_fallo=True), None)
    assert s._conexion_rechazada is None
    assert len(cliente.suscripciones) == 1


def test_desborde_durante_la_escritura_ni_pierde_ni_duplica(almacen, monkeypatch, capsys):
    # El tope descarta por la izquierda MIENTRAS el lote se escribe: el retiro
    # por identidad no debe duplicar, y las filas del lote que el tope tocó
    # quedaron persistidas -> se restan del contador de descartes (sin esto,
    # el evento de auditoría afirmaría un hueco que no existe).
    monkeypatch.setattr(ingestor, "MAX_PENDIENTES", 4)
    s = _servicio(almacen)
    for _ in range(4):
        _recibir(s)
    original = almacen.insertar_lote

    def inserta_y_desborda(vitales, estados):
        original(vitales, estados)
        for _ in range(2):  # llegan mensajes en plena escritura: tope -> pop
            _recibir(s)

    almacen.insertar_lote = inserta_y_desborda
    s._vaciar()
    almacen.insertar_lote = original
    s._vaciar()
    # 4 del lote + 2 llegados durante la escritura: todos persistidos una vez
    assert almacen.contar("vitales") == 6
    assert s._descartados == 0, "lo 'descartado' por el tope estaba persistido"
    eventos = almacen._conn.execute(
        "SELECT detalle FROM eventos_ingesta WHERE evento='descarte'").fetchall()
    assert eventos == [], "sin hueco real no se registra hueco"


def test_registrar_descartes_reintenta_si_el_evento_falla(almacen, monkeypatch, capsys):
    monkeypatch.setattr(ingestor, "MAX_PENDIENTES", 2)
    s = _servicio(almacen)
    for _ in range(4):  # 2 descartes reales
        _recibir(s)
    original = almacen.registrar_evento
    golpes = {"n": 0}

    def falla_una_vez(*a):
        golpes["n"] += 1
        if golpes["n"] == 1:
            raise RuntimeError("disco lleno")
        return original(*a)

    almacen.registrar_evento = falla_una_vez
    s._vaciar()  # el evento falla: se re-acumula
    assert s._descartados == 2, "el descarte no se pierde si el registro falla"
    s._vaciar()  # ahora sí se registra
    detalle = almacen._conn.execute(
        "SELECT detalle FROM eventos_ingesta WHERE evento='descarte'").fetchone()[0]
    assert "2 mensajes" in detalle


def test_hilo_real_encolando_mientras_el_principal_drena(almacen):
    # Ejercita el deque+lock VERDADEROS con un hilo real (no un fake): N
    # productores concurrentes y el principal vaciando — sin perder ni duplicar.
    s = _servicio(almacen)
    total = 200

    def productor():
        for _ in range(total // 2):
            _recibir(s)

    hilos = [threading.Thread(target=productor) for _ in range(2)]
    for h in hilos:
        h.start()
    while any(h.is_alive() for h in hilos):
        s._vaciar()
    for h in hilos:
        h.join()
    s._vaciar()
    assert almacen.contar("vitales") == total
