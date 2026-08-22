"""Parseo puro: contrato 1.1 y 1.0, nulls legítimos, venenos, fidelidad raw."""

import json

from persistencia.ingestor import fila_de_estado, fila_de_vitales

from .conftest import MENSAJE_10, MENSAJE_11, MENSAJE_ESTADO, carga

TOPIC = "monitoreo/vitales/cama-09"
AHORA = "2026-08-22T10:00:02+00:00"


def _fila(mensaje, topic=TOPIC, retenido=False):
    return fila_de_vitales(topic, carga(mensaje), retenido, AHORA)


def test_mensaje_11_fila_exacta():
    f = _fila(MENSAJE_11)
    assert f.contrato == "1.1" and f.cama_id == "cama-09"
    assert f.device_id == "jetson-01" and f.origen == "ocr"
    assert f.ts == "2026-08-22T10:00:00+00:00" and f.recibido_en == AHORA
    assert f.topic == TOPIC and f.retenido == 0 and f.malformado == 0
    assert (f.fc, f.fc_conf) == (142, 0.98)
    assert (f.spo2, f.spo2_conf) == (97, 0.95)
    # null del OCR: valor NULL con confianza 0.0 — semántica clínica, sin marca
    assert (f.fp, f.fp_conf) == (None, 0.0)
    assert (f.fr, f.fr_conf) == (44, 0.91)
    assert (f.temp, f.temp_conf) == (36.8, 0.97)
    assert (f.pni_sis, f.pni_dia, f.pni_media) == (68, 38, 48)
    assert f.pni_conf == 0.9
    assert f.pni_ts == "2026-08-22T09:58:30+00:00"
    assert f.raw == carga(MENSAJE_11)


def test_paridad_con_el_emisor_real_11():
    # Si ocr.contrato cambia de forma, este test lo grita. Import read-only
    # (verificado: no arrastra cv2/numpy).
    from ocr.contrato import construir_mensaje
    lecturas = {
        "fc": (142, 0.98), "spo2": (97, 0.95), "fp": (None, 0.0),
        "fr": (44, 0.91), "temp": (36.8, 0.97),
        "pni_sis": (68, 0.93), "pni_dia": (38, 0.9), "pni_media": (48, 0.95),
    }
    m = construir_mensaje("cama-09", "jetson-01", "2026-08-22T10:00:00+00:00",
                          lecturas)
    f = _fila(m)
    assert f.malformado == 0
    assert (f.fc, f.spo2, f.fp, f.fr, f.temp) == (142, 97, None, 44, 36.8)
    assert (f.pni_sis, f.pni_dia, f.pni_media, f.pni_conf) == (68, 38, 48, 0.9)


def test_paridad_10_simulador_confianzas_null_sin_marca():
    # El simulador publica 1.0 SIN confianza: campo AUSENTE = NULL legítimo,
    # jamás malformado (marcarlo envenenaría el filtro malformado=0 del banco).
    f = _fila(MENSAJE_10, topic="monitoreo/vitales/cama-03")
    assert f.contrato == "1.0" and f.malformado == 0
    assert (f.fc, f.fc_conf) == (138, None)
    assert (f.temp, f.temp_conf) == (36.9, None)
    assert (f.pni_sis, f.pni_conf) == (66, None)
    assert f.pni_ts == "2026-08-22T09:59:40+00:00"


def test_pni_null_todo_null_sin_marca():
    m = {**MENSAJE_11, "signos": {**MENSAJE_11["signos"], "pni": None}}
    f = _fila(m)
    assert (f.pni_sis, f.pni_dia, f.pni_media, f.pni_conf, f.pni_ts) == (None,) * 5
    assert f.malformado == 0


def test_no_json_y_no_objeto_se_saltan():
    assert fila_de_vitales(TOPIC, b"esto no es json", False, AHORA) is None
    assert fila_de_vitales(TOPIC, b"[1,2,3]", False, AHORA) is None
    assert fila_de_vitales(TOPIC, b"\xff\xfe\x00basura", False, AHORA) is None
    assert fila_de_estado(TOPIC, b"null", False, AHORA) is None


def test_bool_no_es_entero_ni_real():
    m = {**MENSAJE_11, "signos": {**MENSAJE_11["signos"],
                                  "fc": {"valor": True, "confianza": 0.9}}}
    f = _fila(m)
    assert f.fc is None and f.malformado == 1
    # par coherente: valor roto -> confianza también NULL (jamás huérfana)
    assert f.fc_conf is None


def test_entero_fuera_de_64_bits_es_veneno_marcado():
    m = {**MENSAJE_11, "signos": {**MENSAJE_11["signos"],
                                  "fc": {"valor": 10 ** 20, "confianza": 0.9}}}
    f = _fila(m)
    assert f.fc is None and f.fc_conf is None and f.malformado == 1


def test_nan_e_infinity_van_a_null_marcado():
    # json.loads acepta NaN/Infinity sin flag: jamás deben llegar a la BD
    payload = carga(MENSAJE_11).replace(b"36.8", b"NaN")
    f = fila_de_vitales(TOPIC, payload, False, AHORA)
    assert f.temp is None and f.malformado == 1
    payload = carga(MENSAJE_11).replace(b"36.8", b"Infinity")
    f = fila_de_vitales(TOPIC, payload, False, AHORA)
    assert f.temp is None and f.malformado == 1


def test_ts_no_string_va_a_null_marcado():
    m = {**MENSAJE_11, "ts": 1755856800}  # epoch: en columna TEXT ordenaría mal
    f = _fila(m)
    assert f.ts is None and f.malformado == 1
    m = {**MENSAJE_11, "ts": {"a": 1}}  # dict: haría lanzar el bind del lote
    f = _fila(m)
    assert f.ts is None and f.malformado == 1


def test_signos_roto_o_ausente():
    f = _fila({**MENSAJE_11, "signos": "basura"})
    assert f.fc is None and f.malformado == 1
    assert f.raw == carga({**MENSAJE_11, "signos": "basura"})
    # sin signos: fundamentalmente roto -> NULLs marcados, raw intacto
    sin = dict(MENSAJE_11)
    del sin["signos"]
    f = _fila(sin)
    assert f.fc is None and f.malformado == 1


def test_valor_string_marcado_y_temp_entera_aceptada():
    m = {**MENSAJE_11, "signos": {**MENSAJE_11["signos"],
                                  "spo2": {"valor": "97", "confianza": 0.9},
                                  "temp": {"valor": 37, "confianza": 0.8}}}
    f = _fila(m)
    assert f.spo2 is None and f.spo2_conf is None and f.malformado == 1
    assert f.temp == 37.0 and f.temp_conf == 0.8  # int -> REAL es forma válida


def test_raw_fiel_byte_a_byte_incluso_no_utf8():
    # el raw es BLOB con los bytes EXACTOS; un JSON válido con bytes latin-1
    # dentro de un string no-UTF8 no parsea, pero un utf-8 válido raro sí
    payload = '{"cama_id": "cama-09", "extra": "ñandú💉"}'.encode("utf-8")
    f = fila_de_vitales(TOPIC, payload, False, AHORA)
    assert f.raw == payload


def test_estado_fila_y_retenido():
    f = fila_de_estado("monitoreo/estado/cama-09", carga(MENSAJE_ESTADO),
                       True, AHORA)
    assert (f.cama_id, f.estado, f.retenido, f.malformado) == ("cama-09", "online", 1, 0)
    assert f.raw == carga(MENSAJE_ESTADO)
    roto = fila_de_estado("monitoreo/estado/cama-09", b'{"estado": 5}', False, AHORA)
    assert roto.estado is None and roto.malformado == 1


def test_retenido_marcado_en_vitales():
    assert _fila(MENSAJE_11, retenido=True).retenido == 1


def test_pni_parcial_por_componente_ausente_se_marca():
    # El contrato emite el trío completo o pni:null ("ni parcial ni
    # incoherente"): una presión parcial sin marca pasaría el filtro de
    # lectura limpia siendo el dato engañoso que el emisor prohíbe.
    m = {**MENSAJE_11, "signos": {**MENSAJE_11["signos"],
                                  "pni": {"dia": 40, "media": 50,
                                          "unidad": "mmHg"}}}
    f = _fila(m)
    assert (f.pni_sis, f.pni_dia, f.pni_media) == (None, 40, 50)
    assert f.malformado == 1


def test_confianza_huerfana_se_marca():
    # Signo-objeto SIN clave "valor" pero con confianza: el par huérfano que
    # el contrato hace imposible — forma rota, conf a NULL.
    m = {**MENSAJE_11, "signos": {**MENSAJE_11["signos"],
                                  "fc": {"confianza": 0.9}}}
    f = _fila(m)
    assert (f.fc, f.fc_conf) == (None, None)
    assert f.malformado == 1
