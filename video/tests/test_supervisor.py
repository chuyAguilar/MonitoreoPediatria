"""La máquina de reinicio: backoff, reset por corrida sana, watchdog de
estancamiento, pin de identidad en relanzamientos, cierre limpio y fatales."""

import pytest

from video import transmisor
from video.transmisor import SupervisorTransmision, TransmisionFatal, pin_de

from .conftest import (
    JIELI,
    JIELI_EN_VIDEO5,
    JIELI_OTRO_PUERTO,
    ULTRASEMI,
    ProcesoFalso,
    RelojFalso,
)


class _Detener(Exception):
    """Corta el bucle desde una costura sin pasar por KeyboardInterrupt."""


def _supervisor(reloj, lanzar, dormir=None, resolver=None, identidad_de=None,
                dispositivo="usb-0:2.2", **cambios):
    esperas = []

    def dormir_defecto(s):
        esperas.append(s)

    base = dict(
        dispositivo=dispositivo, cama_id="cama-09",
        servidor="100.110.157.112", puerto=8554, ancho=1280, alto=720,
        fps=25, bitrate="2M",
        lanzar=lanzar,
        resolver=resolver or (lambda aguja: "/dev/video2"),
        identidad_de=identidad_de or (lambda nodo: JIELI),
        listar=lambda: [ULTRASEMI, JIELI],
        dormir=dormir or dormir_defecto,
        reloj=reloj,
    )
    base.update(cambios)
    sup = SupervisorTransmision(**base)
    sup._esperas_registradas = esperas
    return sup


def test_relanza_con_backoff_progresivo_y_tope():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        if len(lanzados) == 7:
            raise KeyboardInterrupt  # fin del test tras 7 lanzamientos
        p = ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()
    # 1,2,4,8,16,30,30: exponencial con tope de 30 s (fallos inmediatos, sin reset)
    assert sup._esperas_registradas == [1, 2, 4, 8, 16, 30, 30]


def test_salida_con_codigo_cero_tambien_relanza():
    # MediaMTX cerrando "limpio" sigue siendo stream caído: se relanza igual.
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        if lanzados:
            raise KeyboardInterrupt
        p = ProcesoFalso(codigo=0, ticks_vivo=0, reloj=reloj)
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()
    assert len(sup._esperas_registradas) == 1


def test_corrida_sana_resetea_el_backoff():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        n = len(lanzados)
        if n == 3:
            raise KeyboardInterrupt
        if n < 2:
            p = ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)  # fallo rápido
        else:
            # corre 40 s "sano": al_tick renueva el progreso (simula el hilo
            # lector) para que el watchdog no lo derribe
            p = ProcesoFalso(codigo=1, ticks_vivo=40, reloj=reloj,
                             al_tick=lambda: setattr(
                                 sup, "_ultimo_progreso", reloj()))
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()
    # dos fallos rápidos (1, 2) y, tras la corrida sana de 40 s >= 30, reset -> 1
    assert sup._esperas_registradas == [1, 2, 1]


def test_estancamiento_derriba_y_relanza():
    # ffmpeg vivo pero sin progreso (cámara UVC atascada / TCP half-open): a
    # los ~10 s el watchdog lo derriba (terminate) y entra el backoff.
    reloj = RelojFalso()
    lanzados = []
    momento_derribo = []

    def lanzar(argv, con_progreso):
        if lanzados:
            raise KeyboardInterrupt
        p = ProcesoFalso(codigo=1, ticks_vivo=None, reloj=reloj)  # nunca sale solo
        original = p.terminate
        def terminate_registrado():
            momento_derribo.append(reloj())
            original()
        p.terminate = terminate_registrado
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()
    assert lanzados[0].terminado, "el proceso estancado debe recibir terminate"
    # El instante del derribo fija que el umbral usado es TIMEOUT_PROGRESO_S
    # (10 s): primer tick que supera el umbral = t=11 con ticks de 1 s.
    assert momento_derribo == [11]
    assert len(sup._esperas_registradas) == 1


def test_el_timeout_de_progreso_del_constructor_gobierna_el_watchdog():
    # Con timeout_progreso=3, el derribo llega en t=4 (primer tick > 3): fija
    # el wiring del parámetro, no solo su presencia en el constructor.
    reloj = RelojFalso()
    lanzados = []
    momento_derribo = []

    def lanzar(argv, con_progreso):
        if lanzados:
            raise KeyboardInterrupt
        p = ProcesoFalso(codigo=1, ticks_vivo=None, reloj=reloj)
        original = p.terminate
        def terminate_registrado():
            momento_derribo.append(reloj())
            original()
        p.terminate = terminate_registrado
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar, timeout_progreso=3)
    sup.correr()
    assert momento_derribo == [4]


def test_estancamiento_parcial_no_cuenta_como_corrida_sana():
    # 25 s de video real + estancamiento: la duración total (25 + ~11 de
    # detección) supera el umbral sano, pero la transmisión SANA fueron 25 s
    # -> el backoff NO se resetea (una cámara que se congela cada ~25 s no
    # debe girar en caliente a 1 s para siempre).
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        if len(lanzados) == 2:
            raise KeyboardInterrupt
        p = ProcesoFalso(codigo=1, ticks_vivo=None, reloj=reloj)
        ticks = {"n": 0}
        def tick():
            ticks["n"] += 1
            if ticks["n"] <= 25:
                sup._ultimo_progreso = reloj()
        p.al_tick = tick
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()
    # dos ciclos estancados consecutivos: 1 y luego 2 (sin reset intermedio)
    assert sup._esperas_registradas == [1, 2]


def test_estancado_inmatable_es_fatal():
    # Ni SIGKILL lo mata (estado D, driver v4l2 colgado): relanzar abriría
    # otro ffmpeg contra un nodo secuestrado — el supervisor sale ruidoso.
    reloj = RelojFalso()

    def lanzar(argv, con_progreso):
        return ProcesoFalso(codigo=1, ticks_vivo=None, reloj=reloj,
                            ignora_terminate=True, ignora_kill=True)

    sup = _supervisor(reloj, lanzar)
    with pytest.raises(TransmisionFatal, match="SIGKILL"):
        sup.correr()


def test_estancado_que_ignora_terminate_recibe_kill():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        if lanzados:
            raise KeyboardInterrupt
        p = ProcesoFalso(codigo=1, ticks_vivo=None, reloj=reloj,
                         ignora_terminate=True)
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()
    assert lanzados[0].terminado and lanzados[0].matado


def test_ctrl_c_durante_wait_apaga_sin_relanzar():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        p = ProcesoFalso(codigo=1, reloj=reloj, lanza_en_wait=KeyboardInterrupt())
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    sup.correr()  # no debe propagar ni relanzar
    assert len(lanzados) == 1
    assert lanzados[0].terminado, "el finally debe apagar el ffmpeg vivo"
    assert sup._esperas_registradas == []


def test_ctrl_c_durante_backoff_sale_limpio():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        p = ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)
        lanzados.append(p)
        return p

    def dormir(s):
        raise KeyboardInterrupt

    sup = _supervisor(reloj, lanzar, dormir=dormir)
    sup.correr()
    assert len(lanzados) == 1  # el Ctrl+C en la espera no relanza


def test_relanzamiento_re_resuelve_y_sigue_a_la_camara():
    # La cámara "se movió" de nodo entre corridas: el runner la sigue por
    # identidad — y lo hace VERIFICANDO el pin del nodo nuevo, no a ciegas.
    reloj = RelojFalso()
    nodos = iter(["/dev/video2", "/dev/video5"])
    consultados = []
    argvs = []

    def identidad_de(nodo):
        consultados.append(nodo)
        return JIELI if nodo == "/dev/video2" else JIELI_EN_VIDEO5

    def lanzar(argv, con_progreso):
        argvs.append(argv)
        if len(argvs) == 2:
            raise KeyboardInterrupt
        return ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)

    sup = _supervisor(
        reloj, lanzar,
        resolver=lambda aguja: next(nodos),
        identidad_de=identidad_de,
    )
    sup.correr()
    assert argvs[0][argvs[0].index("-i") + 1] == "/dev/video2"
    assert argvs[1][argvs[1].index("-i") + 1] == "/dev/video5"
    # la identidad física del nodo NUEVO se consultó y el pin coincidió
    assert consultados == ["/dev/video2", "/dev/video5"]
    assert sup._pin == pin_de(JIELI)


def test_arranque_sin_identidad_fisica_falla_fuerte():
    # Arranque estricto también para el pin: si la enumeración no confirma el
    # dispositivo, no se transmite (sin pin, los relanzamientos no podrían
    # verificar la fuente — el hueco exacto del incidente de ADR-018).
    reloj = RelojFalso()
    sup = _supervisor(
        reloj,
        lanzar=lambda argv, con_progreso: ProcesoFalso(reloj=reloj),
        identidad_de=lambda nodo: None,
    )
    with pytest.raises(RuntimeError, match="identidad física"):
        sup.correr()


def test_arranque_literal_sin_enumeracion_falla_fuerte():
    reloj = RelojFalso()
    sup = _supervisor(
        reloj,
        lanzar=lambda argv, con_progreso: ProcesoFalso(reloj=reloj),
        dispositivo="/dev/video0",
        identidad_de=lambda nodo: None,
    )
    with pytest.raises(RuntimeError, match="identidad física"):
        sup.correr()


def test_relanzamiento_sin_enumeracion_espera_no_lanza_a_ciegas():
    # Con pin fijado, un relanzamiento donde la enumeración falla (tormenta de
    # re-enumeración USB) NO lanza sin verificar: espera con backoff y relanza
    # cuando la enumeración vuelve. Aplica igual a identidad y a literal.
    for dispositivo in ("usb-0:2.2", "/dev/video2"):
        reloj = RelojFalso()
        fisicos = iter([JIELI, None, JIELI])
        argvs = []

        def lanzar(argv, con_progreso):
            argvs.append(argv)
            if len(argvs) == 2:
                raise KeyboardInterrupt
            return ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)

        sup = _supervisor(
            reloj, lanzar,
            dispositivo=dispositivo,
            identidad_de=lambda nodo: next(fisicos),
        )
        sup.correr()
        # lanzó, falló, la enumeración vacía NO lanzó (espera), volvió y lanzó
        assert len(argvs) == 2, f"con dispositivo={dispositivo!r}"
        assert len(sup._esperas_registradas) == 2


def test_pin_rechaza_otro_dispositivo_fisico_y_espera_al_original():
    # La aguja resuelve, pero a OTRA webcam (misma marca, otro puerto): NO se
    # lanza — se espera a la original con backoff. Cuando vuelve, relanza.
    reloj = RelojFalso()
    fisicos = iter([JIELI, JIELI_OTRO_PUERTO, JIELI])
    intentos_lanzar = []

    def lanzar(argv, con_progreso):
        intentos_lanzar.append(argv)
        if len(intentos_lanzar) == 2:
            # el 2º lanzamiento solo llega cuando el pin vuelve a coincidir
            raise KeyboardInterrupt
        return ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)

    sup = _supervisor(
        reloj, lanzar,
        identidad_de=lambda nodo: next(fisicos),
    )
    sup.correr()
    # secuencia: lanza (original) -> falla -> resolución a OTRO físico: NO
    # lanza, espera -> resolución al original: lanza de nuevo
    assert len(intentos_lanzar) == 2
    assert sup._esperas_registradas == [1, 2]


def test_resolver_falla_a_media_corrida_reintenta():
    reloj = RelojFalso()
    intentos = {"n": 0}

    def resolver(aguja):
        intentos["n"] += 1
        if intentos["n"] == 2:
            raise RuntimeError("No hay ningún dispositivo que coincida")
        return "/dev/video2"

    lanzados = []

    def lanzar(argv, con_progreso):
        if len(lanzados) == 2:
            raise KeyboardInterrupt
        p = ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar, resolver=resolver)
    sup.correr()
    assert len(lanzados) == 2, "tras el fallo transitorio debe relanzar"


def test_resolver_falla_en_el_arranque_propaga():
    # Arranque estricto: identidad ausente -> falla fuerte (el CLI -> exit 1).
    reloj = RelojFalso()
    sup = _supervisor(
        reloj,
        lanzar=lambda argv, con_progreso: ProcesoFalso(reloj=reloj),
        resolver=lambda aguja: (_ for _ in ()).throw(
            RuntimeError("No hay ningún dispositivo")),
    )
    with pytest.raises(RuntimeError):
        sup.correr()


def test_nodo_literal_que_cambia_de_camara_es_fatal():
    # /dev/video0 era la UltraSemi; tras re-enumeración ahora es la Jieli:
    # relanzar transmitiría la cámara equivocada -> TransmisionFatal.
    reloj = RelojFalso()
    fisicos = iter([ULTRASEMI, JIELI])
    lanzados = []

    def lanzar(argv, con_progreso):
        p = ProcesoFalso(codigo=1, ticks_vivo=0, reloj=reloj)
        lanzados.append(p)
        return p

    sup = _supervisor(
        reloj, lanzar,
        dispositivo="/dev/video0",
        identidad_de=lambda nodo: next(fisicos),
    )
    with pytest.raises(TransmisionFatal):
        sup.correr()
    assert len(lanzados) == 1


def test_ffmpeg_desaparecido_es_fatal_accionable():
    reloj = RelojFalso()

    def lanzar(argv, con_progreso):
        raise FileNotFoundError("ffmpeg")

    sup = _supervisor(reloj, lanzar)
    with pytest.raises(TransmisionFatal, match="ffmpeg"):
        sup.correr()


def test_una_vez_no_supervisa_y_devuelve_el_codigo():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        assert con_progreso is False, "--una-vez no captura progreso"
        assert "-progress" not in argv
        p = ProcesoFalso(codigo=3, ticks_vivo=0, reloj=reloj)
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    assert sup.una_vez() == 3
    assert len(lanzados) == 1


def test_una_vez_normaliza_codigos_negativos():
    # ffmpeg muerto por señal devuelve negativo; sys.exit(-15) saldría con
    # 241. Se normaliza a la convención shell 128+N (SIGTERM -> 143).
    reloj = RelojFalso()
    sup = _supervisor(
        reloj,
        lanzar=lambda argv, con_progreso: ProcesoFalso(
            codigo=-15, ticks_vivo=0, reloj=reloj),
    )
    assert sup.una_vez() == 143


def test_una_vez_ctrl_c_apaga_y_devuelve_130():
    reloj = RelojFalso()
    lanzados = []

    def lanzar(argv, con_progreso):
        p = ProcesoFalso(codigo=0, reloj=reloj,
                         lanza_en_wait=KeyboardInterrupt())
        lanzados.append(p)
        return p

    sup = _supervisor(reloj, lanzar)
    assert sup.una_vez() == 130
    assert lanzados[0].terminado, "el ffmpeg de depuración no debe quedar vivo"


def test_hilo_lector_de_progreso_renueva_la_marca():
    # El mecanismo REAL de producción: un stdout con líneas de -progress debe
    # renovar _ultimo_progreso al drenarse (sin esto, todo stream sano se
    # declararía estancado a los ~11 s con la suite en verde).
    reloj = RelojFalso()
    reloj.t = 5.0
    sup = _supervisor(reloj, lanzar=lambda argv, con_progreso: None)
    sup._ultimo_progreso = 0.0
    proc = ProcesoFalso(stdout=iter(["frame=1\n", "out_time=00:00:01\n"]))
    hilo = sup._iniciar_lector_progreso(proc)
    assert hilo is not None
    hilo.join(timeout=5)
    assert not hilo.is_alive()
    assert sup._ultimo_progreso == 5.0


def test_lector_sin_stdout_no_arranca_hilo():
    reloj = RelojFalso()
    sup = _supervisor(reloj, lanzar=lambda argv, con_progreso: None)
    assert sup._iniciar_lector_progreso(ProcesoFalso()) is None


def test_dispositivo_de_nodo_busca_en_la_enumeracion(monkeypatch):
    # El seam por defecto de producción: mapea nodo -> DispositivoCaptura,
    # tolera fallos de enumeración, y normaliza symlinks por realpath.
    from ocr import dispositivos as mod_dispositivos

    monkeypatch.setattr(mod_dispositivos, "listar_dispositivos",
                        lambda: [ULTRASEMI, JIELI])
    assert transmisor._dispositivo_de_nodo("/dev/video2") is JIELI
    assert transmisor._dispositivo_de_nodo("/dev/video0") is ULTRASEMI
    assert transmisor._dispositivo_de_nodo("/dev/video9") is None

    def revienta():
        raise RuntimeError("sin V4L2")
    monkeypatch.setattr(mod_dispositivos, "listar_dispositivos", revienta)
    assert transmisor._dispositivo_de_nodo("/dev/video2") is None
