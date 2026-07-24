"""Construcción del mensaje del contrato de datos 1.1 con origen "ocr".

La forma del mensaje es la de docs/ito2/CONTRATO_DATOS.md más los cambios 1.1
(ARCHITECTURE.md §8): `origen` puede valer "ocr" y cada signo lleva `confianza`
(0-1). Las unidades son fijas por contrato: no se cambian sin subir la versión.
"""

VERSION_CONTRATO = "1.1"
ORIGEN = "ocr"

# Signos que se emiten como objeto {valor, unidad, confianza}
SIGNOS_SIMPLES = ("fc", "spo2", "fp", "fr", "temp")

# Componentes que se leen por separado (ROIs propias) y se agrupan en `pni`
COMPONENTES_PNI = ("pni_sis", "pni_dia", "pni_media")

# Unidades fijas del contrato, por clave de lectura
UNIDADES_CONTRATO = {
    "fc": "lpm",
    "spo2": "%",
    "fp": "lpm",
    "fr": "rpm",
    "temp": "C",
    "pni_sis": "mmHg",
    "pni_dia": "mmHg",
    "pni_media": "mmHg",
}


# Holgura (mmHg) al comparar la media con sistólica y diastólica: absorbe el
# redondeo con que el propio monitor calcula la presión arterial media.
TOLERANCIA_PNI_MMHG = 2


def _pni_coherente(sis, dia, media) -> bool:
    """Orden fisiológico obligatorio: dia < sis y dia <= media <= sis.

    Cada componente se valida por separado contra su propio rango de
    plausibilidad, y esos rangos se solapan mucho. Por eso un solo dígito mal
    leído produce un trío en el que cada número es plausible por su cuenta pero
    imposible en conjunto (p. ej. 40/75 con media 90, o una presión invertida
    75/120). Sería tan engañoso como una presión parcial, así que se descarta
    igual: la regla es "ni parcial ni incoherente".
    """
    if dia >= sis:
        return False
    return (dia - TOLERANCIA_PNI_MMHG) <= media <= (sis + TOLERANCIA_PNI_MMHG)


def construir_mensaje(cama_id: str, device_id: str, ts: str, lecturas: dict) -> dict:
    """Arma el mensaje del contrato 1.1 a partir de las lecturas del OCR.

    `lecturas` mapea cada clave de UNIDADES_CONTRATO a una tupla
    (valor | None, confianza). Un valor None significa "no leído / descartado"
    y siempre viaja con confianza 0.0.
    """
    faltantes = [c for c in UNIDADES_CONTRATO if c not in lecturas]
    if faltantes:
        raise ValueError(f"Faltan lecturas para: {', '.join(faltantes)}")

    signos = {}
    for clave in SIGNOS_SIMPLES:
        valor, confianza = lecturas[clave]
        signos[clave] = {
            "valor": valor,
            "unidad": UNIDADES_CONTRATO[clave],
            "confianza": 0.0 if valor is None else confianza,
        }

    # PNI: o los tres componentes legibles y coherentes entre sí, o nada. Una
    # tensión parcial o imposible es clínicamente engañosa, así que nunca se
    # emite (CONTEXT.md §1: no presentar lecturas dudosas).
    componentes = [lecturas[c] for c in COMPONENTES_PNI]
    valores = [valor for valor, _ in componentes]
    if any(valor is None for valor in valores) or not _pni_coherente(*valores):
        signos["pni"] = None
    else:
        signos["pni"] = {
            "sis": componentes[0][0],
            "dia": componentes[1][0],
            "media": componentes[2][0],
            "unidad": "mmHg",
            # TODO(pipeline en vivo): rastrear el ts real de la última medición
            # de PNI (cambia solo cuando el monitor vuelve a medir). En imagen
            # fija no hay información temporal: se usa el ts del mensaje.
            "ts": ts,
            "confianza": min(confianza for _, confianza in componentes),
        }

    return {
        "contrato": VERSION_CONTRATO,
        "cama_id": cama_id,
        "device_id": device_id,
        "ts": ts,
        "origen": ORIGEN,
        "signos": signos,
    }
