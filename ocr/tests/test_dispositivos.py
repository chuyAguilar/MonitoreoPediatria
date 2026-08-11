"""Resolución de la capturadora por identidad estable, sin hardware (ADR-018).

Las costuras de lectura del sistema (_nodos_video, _grupo_fisico, etc.) se
mockean con un árbol falso que replica el incidente del banco: una webcam en
/dev/video0 y la capturadora UltraSemi en /dev/video2 (captura) + /dev/video3
(metadatos), con los nombres y symlinks reales medidos por la sonda en la
Jetson. Un único test toca hardware real y se salta fuera de Linux/V4L2.
"""

from pathlib import Path

import pytest

from ocr import dispositivos
from ocr.dispositivos import (
    V4L2_CAP_META_CAPTURE,
    V4L2_CAP_VIDEO_CAPTURE,
    formatear_tabla,
    listar_dispositivos,
    resolver,
)

CAP = V4L2_CAP_VIDEO_CAPTURE
META = V4L2_CAP_META_CAPTURE

# Réplica del banco (10 ago 2026), con los datos reales de la sonda:
# la webcam robó video0; la capturadora quedó en video2 (captura) y video3
# (metadatos). El nombre de tarjeta de la UltraSemi NO contiene "UltraSemi"
# (solo el by-id lo trae) y es idéntico en sus dos nodos.
ARBOL_INCIDENTE = {
    "grupo-webcam": {
        "nombre": "HD Webcam C270",
        "nodos": {"/dev/video0": CAP, "/dev/video1": META},
        "by_id": "usb-Logitech_HD_Webcam_C270_A1B2C3D4",
        "by_path": "platform-3610000.usb-usb-0:1.1:1.0",
    },
    "grupo-capturadora": {
        "nombre": "USB3 Video: USB3 Video",
        "nodos": {"/dev/video2": CAP, "/dev/video3": META},
        "by_id": "usb-UltraSemi_USB3_Video_35562055",
        "by_path": "platform-3610000.usb-usb-0:1.3:1.0",
    },
}


def _montar(monkeypatch, arbol):
    """Instala el árbol falso en las costuras de ocr.dispositivos."""
    nodo_a_grupo = {}
    nodo_a_caps = {}
    nodo_a_nombre = {}
    by_id = []
    by_path = []
    for grupo, d in arbol.items():
        for i, (nodo, caps) in enumerate(sorted(d["nodos"].items())):
            nodo_a_grupo[nodo] = grupo
            nodo_a_caps[nodo] = caps
            nodo_a_nombre[nodo] = d["nombre"]
            if d.get("by_id"):
                by_id.append((f"{d['by_id']}-video-index{i}", nodo))
            if d.get("by_path"):
                by_path.append((f"{d['by_path']}-video-index{i}", nodo))

    monkeypatch.setattr(dispositivos, "_hay_v4l2", lambda: True)
    monkeypatch.setattr(dispositivos, "_nodos_video", lambda: sorted(nodo_a_grupo))
    monkeypatch.setattr(dispositivos, "_grupo_fisico", nodo_a_grupo.__getitem__)
    monkeypatch.setattr(dispositivos, "_capacidades", nodo_a_caps.__getitem__)
    monkeypatch.setattr(dispositivos, "_nombre_de_tarjeta", nodo_a_nombre.__getitem__)
    monkeypatch.setattr(
        dispositivos, "_entradas_estables",
        lambda directorio: by_id if "by-id" in directorio else by_path,
    )


# --------------------------------------------------------------------------
# Regresión directa del incidente
# --------------------------------------------------------------------------


def test_resuelve_por_serial_al_nodo_de_captura(monkeypatch):
    _montar(monkeypatch, ARBOL_INCIDENTE)
    assert resolver("35562055") == "/dev/video2"


def test_resuelve_por_modelo_con_la_webcam_conectada(monkeypatch):
    """El escenario del banco: con la webcam en video0, 'UltraSemi' debe ir a
    la capturadora — jamás al video0 que se leyó por error aquel día."""
    _montar(monkeypatch, ARBOL_INCIDENTE)
    assert resolver("UltraSemi") == "/dev/video2"


def test_match_insensible_a_mayusculas(monkeypatch):
    _montar(monkeypatch, ARBOL_INCIDENTE)
    assert resolver("ultrasemi") == "/dev/video2"
    assert resolver("uSb3_vIdEo_355") == "/dev/video2"


def test_resuelve_por_by_path(monkeypatch):
    """El puerto físico es identidad válida: el desempate multi-cama futuro."""
    _montar(monkeypatch, ARBOL_INCIDENTE)
    assert resolver("usb-0:1.3") == "/dev/video2"


def test_identidad_ausente_falla_fuerte_sin_fallback(monkeypatch):
    """La regla de oro de ADR-018: identidad no presente → error accionable.

    Nada de caer a /dev/video0 (eso fue exactamente leer la webcam)."""
    _montar(monkeypatch, ARBOL_INCIDENTE)
    with pytest.raises(RuntimeError) as exc:
        resolver("Elgato")
    mensaje = str(exc.value)
    assert "Elgato" in mensaje                  # qué se buscó
    assert "35562055" in mensaje                # qué hay disponible
    assert "--listar-dispositivos" in mensaje   # cómo descubrirlo
    assert "NO se cae a /dev/video0" in mensaje


def test_ambiguedad_exige_desambiguar(monkeypatch):
    """Dos dispositivos que coinciden → error que lista los by-path de ambos."""
    _montar(monkeypatch, ARBOL_INCIDENTE)
    with pytest.raises(RuntimeError) as exc:
        # específico (pasa la guardia anti-genéricos) pero presente en el
        # by-path de AMBOS dispositivos: el mismo controlador USB
        resolver("platform-3610000")
    mensaje = str(exc.value)
    assert "ambiguo" in mensaje
    assert "usb-0:1.1" in mensaje and "usb-0:1.3" in mensaje


def test_nodo_por_capacidad_no_por_convencion(monkeypatch):
    """Si udev numerara al revés (index0 = metadatos), QUERYCAP manda igual.

    El nombre de tarjeta es idéntico en ambos nodos (medido en la Jetson), así
    que la capacidad real es el ÚNICO criterio válido."""
    arbol = {
        "grupo-rara": {
            "nombre": "USB3 Video: USB3 Video",
            "nodos": {"/dev/video4": META, "/dev/video5": CAP},  # ¡captura en el 2º!
            "by_id": "usb-UltraSemi_USB3_Video_35562055",
            "by_path": "platform-x-usb-0:1.3:1.0",
        },
    }
    _montar(monkeypatch, arbol)
    assert resolver("35562055") == "/dev/video5"


def test_dispositivo_sin_nodo_de_captura(monkeypatch):
    arbol = {
        "grupo-meta": {
            "nombre": "Solo Metadatos",
            "nodos": {"/dev/video6": META},
            "by_id": "usb-Rara_Meta_99",
            "by_path": "",
        },
    }
    _montar(monkeypatch, arbol)
    with pytest.raises(RuntimeError, match="capacidad de captura"):
        resolver("Rara_Meta")


def test_plataforma_sin_v4l2_da_error_claro(monkeypatch):
    monkeypatch.setattr(dispositivos, "_hay_v4l2", lambda: False)
    with pytest.raises(RuntimeError, match="Linux/V4L2"):
        resolver("35562055")


# --------------------------------------------------------------------------
# Endurecimiento tras la revisión adversarial: la clase de fallo "capturadora
# ausente + identificador poco específico → se abre otra fuente en silencio"
# --------------------------------------------------------------------------

# Solo la webcam conectada (capturadora desenumerada): el escenario post-corte
ARBOL_SOLO_WEBCAM = {
    "grupo-webcam": {
        "nombre": "USB3.0 Camera",  # nombre genérico real de webcams baratas
        "nodos": {"/dev/video0": CAP, "/dev/video1": META},
        "by_id": "usb-Generic_USB3.0_Camera_0001",
        "by_path": "platform-3610000.usb-usb-0:1.1:1.0",
    },
}


@pytest.mark.parametrize("generico", ["usb", "usb3", "cam", "camera", "video", "platform", "hdmi"])
def test_identificador_generico_se_rechaza_aunque_haya_un_solo_match(monkeypatch, generico):
    """Con la capturadora ausente, "usb3" coincidiría SOLO con la webcam
    'USB3.0 Camera' y la abriría en silencio — la clase exacta del incidente.
    Por eso los identificadores genéricos se rechazan en el arranque."""
    _montar(monkeypatch, ARBOL_SOLO_WEBCAM)
    with pytest.raises(RuntimeError, match="demasiado genérico"):
        resolver(generico)


def test_identificadores_especificos_siguen_funcionando(monkeypatch):
    """La guardia de especificidad no puede romper los identificadores del runbook."""
    _montar(monkeypatch, ARBOL_INCIDENTE)
    assert resolver("35562055") == "/dev/video2"
    assert resolver("UltraSemi") == "/dev/video2"
    assert resolver("usb-0:1.3") == "/dev/video2"


def test_el_match_no_cruza_campos(monkeypatch):
    """El match es campo por campo: '35562055 platform' no debe resolver
    (con el haystack concatenado por espacios sí lo hacía)."""
    _montar(monkeypatch, ARBOL_INCIDENTE)
    with pytest.raises(RuntimeError, match="ningún dispositivo"):
        resolver("35562055 platform")


def test_dos_nodos_de_captura_fallan_fuerte(monkeypatch):
    """Capturadora dual-HDMI: elegir una entrada en silencio podría leer la
    entrada sin señal. Misma disciplina que la ambigüedad entre dispositivos."""
    arbol = {
        "grupo-dual": {
            "nombre": "Dual HDMI Capture",
            "nodos": {"/dev/video2": CAP, "/dev/video3": META, "/dev/video10": CAP},
            "by_id": "usb-Dual_HDMI_77777777",
            "by_path": "platform-x-usb-0:1.4:1.0",
        },
    }
    _montar(monkeypatch, arbol)
    with pytest.raises(RuntimeError) as exc:
        resolver("77777777")
    mensaje = str(exc.value)
    assert "/dev/video2" in mensaje and "/dev/video10" in mensaje
    assert "ruta explícita" in mensaje


def test_nodos_en_orden_numerico_natural(monkeypatch):
    """'video10' va DESPUÉS de 'video2': el orden lexicográfico los invertiría
    (y con él, cualquier elección posicional caería en el nodo equivocado)."""
    arbol = {
        "grupo-dual": {
            "nombre": "Dual",
            "nodos": {"/dev/video10": META, "/dev/video2": CAP},
            "by_id": "usb-Dual_88888888",
            "by_path": "",
        },
    }
    _montar(monkeypatch, arbol)
    detectado = listar_dispositivos()[0]
    assert [n for n, _ in detectado.nodos] == ["/dev/video2", "/dev/video10"]
    assert detectado.nodo_captura == "/dev/video2"


# --------------------------------------------------------------------------
# Enumeración y tabla
# --------------------------------------------------------------------------


def test_listar_agrupa_nodos_por_dispositivo_fisico(monkeypatch):
    _montar(monkeypatch, ARBOL_INCIDENTE)
    detectados = listar_dispositivos()
    assert len(detectados) == 2
    capturadora = next(d for d in detectados if d.serial == "35562055")
    assert capturadora.nodo_captura == "/dev/video2"
    assert [n for n, _ in capturadora.nodos] == ["/dev/video2", "/dev/video3"]
    assert capturadora.by_id == "usb-UltraSemi_USB3_Video_35562055"
    assert capturadora.by_path == "platform-3610000.usb-usb-0:1.3:1.0"


def test_tabla_muestra_lo_que_el_operador_necesita(monkeypatch):
    _montar(monkeypatch, ARBOL_INCIDENTE)
    tabla = formatear_tabla(listar_dispositivos())
    assert "35562055" in tabla                      # serial utilizable
    assert "/dev/video2[captura]" in tabla          # nodo correcto marcado
    assert "/dev/video3[metadatos]" in tabla        # el de metadatos, señalado
    assert "usb-UltraSemi_USB3_Video_35562055" in tabla


def test_serial_best_effort():
    assert dispositivos._serial_de("usb-UltraSemi_USB3_Video_35562055") == "35562055"
    assert dispositivos._serial_de("") == ""


# --------------------------------------------------------------------------
# Hardware real: solo corre en Linux con V4L2 (la Jetson)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not Path("/dev/v4l").exists(), reason="sin hardware V4L2")
def test_smoke_enumeracion_real():
    detectados = listar_dispositivos()
    for d in detectados:
        for nodo, _caps in d.nodos:
            assert nodo.startswith("/dev/video")
