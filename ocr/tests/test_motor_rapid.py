"""Motor de producción RapidOCR/ONNX Runtime (ADR-017).

Dos capas deliberadamente separadas:

- **Capa mock** (corre SIEMPRE, sin la dependencia): un módulo falso
  `rapidocr_onnxruntime` inyectado en sys.modules prueba la lógica del
  ADAPTADOR aislada — mapeo texto/score, saneo, casos de borde — con la forma
  de retorno verificada por sonda contra la 1.4.4 real:
      engine(img, use_det=False, use_cls=False, use_rec=True)
        -> ([[texto, score]], [tiempos])
- **Capa real** (skip sin la dependencia): el engine de verdad leyendo
  dígitos dibujados y el frame real, más motor_por_defecto().
"""

import sys
import types

import numpy as np
import pytest

from ocr import digitos
from ocr.lector import motor_por_defecto


def _recorte_color(texto, alto=80):
    """Número blanco sobre fondo oscuro, como en un monitor (recorte BGR crudo)."""
    binaria = digitos.dibujar_numero(texto, alto)
    lienzo = np.full((binaria.shape[0] + 30, binaria.shape[1] + 30, 3), 12, dtype=np.uint8)
    region = lienzo[15:15 + binaria.shape[0], 15:15 + binaria.shape[1]]
    region[binaria > 0] = (240, 240, 240)
    return lienzo


# --------------------------------------------------------------------------
# Capa MOCK: la lógica del adaptador, sin el binario (corre en cualquier CI)
# --------------------------------------------------------------------------


def _motor_con_engine_falso(monkeypatch, respuesta):
    """Construye LectorRapidOCR contra un rapidocr_onnxruntime falso.

    `respuesta` es lo que devuelve engine(...) — la tupla (resultado, tiempos)
    con la forma verificada por la sonda — o una función(img) para variarla.
    """
    llamadas = []

    class EngineFalso:
        def __call__(self, img, use_det=None, use_cls=None, use_rec=None):
            llamadas.append({"img": img, "use_det": use_det,
                             "use_cls": use_cls, "use_rec": use_rec})
            return respuesta(img) if callable(respuesta) else respuesta

    modulo = types.ModuleType("rapidocr_onnxruntime")
    modulo.RapidOCR = EngineFalso
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", modulo)
    monkeypatch.delitem(sys.modules, "ocr.motor.rapid", raising=False)
    from ocr.motor.rapid import LectorRapidOCR
    return LectorRapidOCR(), llamadas


def test_mock_pide_rec_only(monkeypatch):
    """Las ROIs ya aíslan el número: sin detección ni clasificación de ángulo."""
    motor, llamadas = _motor_con_engine_falso(monkeypatch, ([["73", 0.99]], [0.01]))
    motor.leer(_recorte_color("73"))
    assert llamadas[0]["use_det"] is False
    assert llamadas[0]["use_cls"] is False
    assert llamadas[0]["use_rec"] is True


def test_mock_mapea_texto_y_score(monkeypatch):
    motor, _ = _motor_con_engine_falso(monkeypatch, ([["120/75", 0.9995]], [0.01]))
    assert motor.leer(_recorte_color("1")) == ("120/75", 0.9995)


def test_mock_imagen_vacia_del_engine(monkeypatch):
    """La 1.4.4 real devuelve [['', 0.0]] ante imagen negra → (None, 0.0)."""
    motor, _ = _motor_con_engine_falso(monkeypatch, ([["", 0.0]], [0.01]))
    assert motor.leer(_recorte_color("1")) == (None, 0.0)


@pytest.mark.parametrize("respuesta", [(None, None), ([], []), (None, [0.01])])
def test_mock_resultado_nulo_o_vacio(monkeypatch, respuesta):
    motor, _ = _motor_con_engine_falso(monkeypatch, respuesta)
    assert motor.leer(_recorte_color("1")) == (None, 0.0)


def test_mock_entrada_none_o_vacia_no_llama_al_engine(monkeypatch):
    motor, llamadas = _motor_con_engine_falso(monkeypatch, ([["9", 0.9]], [0.01]))
    assert motor.leer(None) == (None, 0.0)
    assert motor.leer(np.empty((0, 0, 3), dtype=np.uint8)) == (None, 0.0)
    assert llamadas == []


def test_mock_solo_quita_espacios(monkeypatch):
    """Saneo mínimo: espacios fuera, letras DENTRO (las rechaza el lector)."""
    motor, _ = _motor_con_engine_falso(monkeypatch, ([[" 12 O ", 0.9]], [0.01]))
    texto, _ = motor.leer(_recorte_color("1"))
    assert texto == "12O"          # la 'O' se conserva → _interpretar la rechaza


def test_mock_multientrada_concatena_y_toma_score_minimo(monkeypatch):
    """Si una versión partiera el campo, orden + min(score): la peor pieza manda."""
    motor, _ = _motor_con_engine_falso(
        monkeypatch, ([["120", 0.99], ["/75", 0.61]], [0.01, 0.01])
    )
    assert motor.leer(_recorte_color("1")) == ("120/75", 0.61)


def test_mock_score_no_convertible(monkeypatch):
    motor, _ = _motor_con_engine_falso(monkeypatch, ([["74", "alta"]], [0.01]))
    assert motor.leer(_recorte_color("1")) == (None, 0.0)


def test_mock_score_no_convertible_en_multientrada_descarta_todo(monkeypatch):
    """Una pieza con score corrupto invalida la lectura ENTERA, no solo la pieza.

    Si se descartara solo esa pieza, "120"+"75" con el score del "75" roto se
    publicaría como "120" — un número truncado inventado. Mata al mutante
    `return (None, 0.0) → continue` en el adaptador.
    """
    motor, _ = _motor_con_engine_falso(
        monkeypatch, ([["120", 0.99], ["/75", "mala"]], [0.01, 0.01])
    )
    assert motor.leer(_recorte_color("1")) == (None, 0.0)


def test_mock_pasa_buffer_contiguo(monkeypatch):
    motor, llamadas = _motor_con_engine_falso(monkeypatch, ([["7", 0.9]], [0.01]))
    vista = _recorte_color("7")[5:60, 5:80]      # vista no contigua
    assert not vista.flags["C_CONTIGUOUS"]
    motor.leer(vista)
    assert llamadas[0]["img"].flags["C_CONTIGUOUS"]


# --------------------------------------------------------------------------
# Capa REAL: el engine de verdad. El importorskip vive DENTRO del fixture (no
# a nivel de módulo): un importorskip de módulo abortaría la colección del
# archivo entero y se llevaría por delante la capa mock de arriba, que debe
# correr justamente donde la dependencia no está.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rapid():
    pytest.importorskip("rapidocr_onnxruntime", reason="motor de producción no instalado")
    from ocr.motor.rapid import LectorRapidOCR
    return LectorRapidOCR()


@pytest.mark.parametrize("texto", ["74", "98", "120/75", "36.8"])
def test_lee_numeros_de_un_recorte_crudo(rapid, texto):
    leido, confianza = rapid.leer(_recorte_color(texto))
    assert leido == texto
    assert 0.0 <= confianza <= 1.0
    assert confianza > 0.6


def test_confianza_siempre_en_dominio(rapid):
    """El adaptador entrega confianza en [0,1]; _confianza_valida es la última red."""
    for texto in ("74", "120/75", "888"):
        _, confianza = rapid.leer(_recorte_color(texto))
        assert 0.0 <= confianza <= 1.0


def test_roi_en_blanco_no_inventa(rapid):
    leido, confianza = rapid.leer(np.full((90, 160, 3), 12, dtype=np.uint8))
    assert leido is None
    assert confianza == 0.0


def test_acepta_entrada_en_gris(rapid):
    import cv2
    gris = cv2.cvtColor(_recorte_color("98"), cv2.COLOR_BGR2GRAY)
    leido, confianza = rapid.leer(gris)
    assert leido == "98"
    assert confianza > 0.6


def test_no_alucina_digitos_de_texto_no_numerico(rapid):
    """Sobre una ROI con letras, el adaptador no debe producir un número válido.

    O devuelve None, o devuelve un texto con letras que el lector rechaza. Lo
    que no puede es inventar dígitos limpios (ver la regla de oro).
    """
    import cv2
    etiqueta = np.full((60, 200, 3), 12, dtype=np.uint8)
    cv2.putText(etiqueta, "NIBP", (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (240, 240, 240), 3, cv2.LINE_AA)
    leido, _ = rapid.leer(etiqueta)
    assert leido is None or not leido.replace(".", "").replace("/", "").isdigit()


def test_motor_por_defecto_devuelve_rapidocr():
    """La producción es RapidOCR (ADR-017), no Paddle ni plantilla."""
    pytest.importorskip("rapidocr_onnxruntime", reason="motor de producción no instalado")
    from ocr.motor.rapid import LectorRapidOCR
    assert isinstance(motor_por_defecto(), LectorRapidOCR)
