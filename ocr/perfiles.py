"""Carga y validación de perfiles de monitor (ROIs por signo).

Un perfil es un JSON declarativo que describe, para un modelo de monitor, la
caja [x, y, w, h] donde aparece cada signo, su tipo de dato, unidad y rango de
plausibilidad. Los ROIs se definen a mano por modelo (ADR-002: cambiar de
monitor exige reajustar regiones).

Nota sobre `rango`: es un rango de PLAUSIBILIDAD FISIOLÓGICA (amplio), pensado
para descartar basura del OCR (p. ej. una FC de 999 por lectura fantasma).
NO es el "rango neonatal típico" del contrato, que es descriptivo: un valor
anormal pero real (p. ej. bradicardia de 80 lpm) debe mostrarse, no ocultarse.

Campos opcionales (iteración 2, aditivos: su ausencia = comportamiento previo):
- `presente: false` — el monitor no muestra ese signo. No lleva ROI y el lector
  lo emite como null + confianza 0 sin intentar OCR.
- `separador` + `parte` — el signo se lee de un campo combinado (p. ej. la PNI
  de SimCore, "120/75"): se lee el ROI una vez, se parte el texto por el
  separador y se toma el componente `parte` (0 = izquierda, 1 = derecha). Dos
  signos pueden compartir el mismo ROI con distinta `parte`.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from ocr.contrato import UNIDADES_CONTRATO

TIPOS_VALIDOS = ("int", "float")

# Pares de un campo combinado con orden semántico obligatorio.
PARES_ORDENADOS = (("pni_sis", "pni_dia"),)


class PerfilInvalido(ValueError):
    """El archivo de perfil no cumple el esquema esperado."""


@dataclass(frozen=True)
class SignoPerfil:
    unidad: str           # fija por contrato (se valida contra UNIDADES_CONTRATO)
    presente: bool = True # False = el monitor no muestra este signo
    roi: tuple = None     # (x, y, w, h) en píxeles; None si el signo está ausente
    tipo: str = None      # "int" | "float"
    rango: tuple = None   # (mínimo, máximo) de plausibilidad fisiológica
    decimales: int = 0    # decimales esperados (solo informativo para float)
    separador: str = None # si el campo es combinado, carácter que separa (p. ej. "/")
    parte: int = None     # 0 = antes del separador, 1 = después


@dataclass(frozen=True)
class Perfil:
    nombre: str
    resolucion: tuple     # (ancho, alto) de la imagen que el perfil describe
    signos: dict = field(default_factory=dict)


def cargar_perfil(ruta) -> Perfil:
    """Lee un perfil desde un archivo JSON y lo valida."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return perfil_desde_dict(datos)


def perfil_desde_dict(datos: dict) -> Perfil:
    """Valida el dict de un perfil y lo convierte a Perfil. Lanza PerfilInvalido."""
    nombre = datos.get("perfil")
    if not isinstance(nombre, str) or not nombre:
        raise PerfilInvalido("El perfil necesita un campo 'perfil' (nombre) no vacío")

    resolucion = datos.get("resolucion")
    if (
        not isinstance(resolucion, (list, tuple))
        or len(resolucion) != 2
        or not all(isinstance(v, int) and v > 0 for v in resolucion)
    ):
        raise PerfilInvalido("'resolucion' debe ser [ancho, alto] con enteros positivos")
    ancho_img, alto_img = resolucion

    signos_datos = datos.get("signos")
    if not isinstance(signos_datos, dict):
        raise PerfilInvalido("El perfil necesita un objeto 'signos'")

    faltantes = sorted(set(UNIDADES_CONTRATO) - set(signos_datos))
    if faltantes:
        raise PerfilInvalido(f"Faltan signos en el perfil: {', '.join(faltantes)}")

    desconocidos = sorted(set(signos_datos) - set(UNIDADES_CONTRATO))
    if desconocidos:
        raise PerfilInvalido(f"Signos desconocidos en el perfil: {', '.join(desconocidos)}")

    signos = {}
    for clave, cfg in signos_datos.items():
        signos[clave] = _validar_signo(clave, cfg, ancho_img, alto_img)

    _validar_campos_compartidos(signos)

    return Perfil(nombre=nombre, resolucion=(ancho_img, alto_img), signos=signos)


def _validar_campos_compartidos(signos: dict) -> None:
    """Dos signos solo pueden mirar el mismo sitio si son un campo combinado.

    Atrapa los errores de copiar/pegar al calibrar. Todos acaban igual: dos
    signos que publican el mismo número como si fueran mediciones
    independientes. Es especialmente grave entre FC y FP, porque que ambas
    concuerden es justo el control de calidad de la señal del oxímetro: si FP
    es una copia de FC, ese control "concuerda" siempre.

    Se comprueba **solapamiento**, no igualdad exacta: un ROI desplazado un
    píxel al recalibrar leería el mismo número y evadiría una comparación
    estricta.
    """
    presentes = [(clave, s) for clave, s in signos.items() if s.presente]
    for i, (clave_a, a) in enumerate(presentes):
        for clave_b, b in presentes[i + 1:]:
            if not _se_solapan(a.roi, b.roi):
                continue
            if _es_campo_combinado(a, b):
                continue
            if a.roi == b.roi and a.separador is not None and a.parte == b.parte:
                raise PerfilInvalido(
                    f"'{clave_a}' y '{clave_b}' leen exactamente la misma parte "
                    f"({a.parte}) del mismo campo combinado {list(a.roi)}"
                )
            raise PerfilInvalido(
                f"'{clave_a}' {list(a.roi)} y '{clave_b}' {list(b.roi)} se solapan "
                f"sin ser un campo combinado: publicarían el mismo número"
            )

    _validar_orden_combinado(signos)


def _es_campo_combinado(a: SignoPerfil, b: SignoPerfil) -> bool:
    """Único solapamiento legítimo: el mismo campo leído por sus dos mitades."""
    return (
        a.roi == b.roi
        and a.separador is not None
        and a.separador == b.separador
        and a.parte != b.parte
    )


def _se_solapan(roi_a: tuple, roi_b: tuple) -> bool:
    ax, ay, aw, ah = roi_a
    bx, by, bw, bh = roi_b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _validar_orden_combinado(signos: dict) -> None:
    """La sistólica va antes del separador: "120/75", nunca al revés.

    Los rangos de sis y dia se solapan, así que una presión invertida pasaría
    la validación de rango y se publicaría con confianza alta.
    """
    for izquierda, derecha in PARES_ORDENADOS:
        a, b = signos.get(izquierda), signos.get(derecha)
        if a is None or b is None or not (a.presente and b.presente):
            continue
        if a.separador is None or b.separador is None or a.roi != b.roi:
            continue
        if a.parte > b.parte:
            raise PerfilInvalido(
                f"'{izquierda}' lee la parte {a.parte} y '{derecha}' la {b.parte} "
                f"del campo {list(a.roi)}: están invertidos. La sistólica va antes "
                f"del separador '{a.separador}' (convención SIS/DIA)"
            )


def _validar_signo(clave: str, cfg: dict, ancho_img: int, alto_img: int) -> SignoPerfil:
    if not isinstance(cfg, dict):
        raise PerfilInvalido(f"'{clave}': debe ser un objeto")

    unidad = cfg.get("unidad", UNIDADES_CONTRATO[clave])
    if unidad != UNIDADES_CONTRATO[clave]:
        raise PerfilInvalido(
            f"'{clave}': unidad '{unidad}' no coincide con la del contrato "
            f"('{UNIDADES_CONTRATO[clave]}'); las unidades son fijas por contrato"
        )

    presente = cfg.get("presente", True)
    if not isinstance(presente, bool):
        raise PerfilInvalido(f"'{clave}': 'presente' debe ser true o false")

    if not presente:
        # Un signo ausente no se lee: no lleva ROI ni parámetros de lectura.
        sobrantes = sorted({"roi", "tipo", "rango", "separador", "parte"} & set(cfg))
        if sobrantes:
            raise PerfilInvalido(
                f"'{clave}': un signo ausente (presente: false) no lleva "
                f"{', '.join(sobrantes)}"
            )
        return SignoPerfil(unidad=unidad, presente=False)

    roi = cfg.get("roi")
    if (
        not isinstance(roi, (list, tuple))
        or len(roi) != 4
        or not all(isinstance(v, int) for v in roi)
    ):
        raise PerfilInvalido(f"'{clave}': 'roi' debe ser [x, y, w, h] con enteros")
    x, y, w, h = roi
    if w <= 0 or h <= 0:
        raise PerfilInvalido(f"'{clave}': ROI con ancho/alto no positivos: {roi}")
    if x < 0 or y < 0 or x + w > ancho_img or y + h > alto_img:
        raise PerfilInvalido(
            f"'{clave}': ROI {roi} fuera de la resolución {ancho_img}x{alto_img}"
        )

    tipo = cfg.get("tipo")
    if tipo not in TIPOS_VALIDOS:
        raise PerfilInvalido(f"'{clave}': 'tipo' debe ser uno de {TIPOS_VALIDOS}")

    rango = cfg.get("rango")
    if (
        not isinstance(rango, (list, tuple))
        or len(rango) != 2
        or not all(isinstance(v, (int, float)) for v in rango)
        or rango[0] >= rango[1]
    ):
        raise PerfilInvalido(f"'{clave}': 'rango' debe ser [mínimo, máximo] con mínimo < máximo")

    decimales = cfg.get("decimales", 0)
    if not isinstance(decimales, int) or decimales < 0:
        raise PerfilInvalido(f"'{clave}': 'decimales' debe ser un entero >= 0")

    separador, parte = _validar_campo_combinado(clave, cfg)

    return SignoPerfil(
        unidad=unidad,
        presente=True,
        roi=(x, y, w, h),
        tipo=tipo,
        rango=(rango[0], rango[1]),
        decimales=decimales,
        separador=separador,
        parte=parte,
    )


def _validar_campo_combinado(clave: str, cfg: dict) -> tuple:
    """Valida 'separador'/'parte'. Devuelve (None, None) si no es campo combinado."""
    separador = cfg.get("separador")
    parte = cfg.get("parte")

    if separador is None and parte is None:
        return None, None
    if separador is None or parte is None:
        raise PerfilInvalido(
            f"'{clave}': 'separador' y 'parte' van siempre juntos"
        )
    if not isinstance(separador, str) or len(separador) != 1:
        raise PerfilInvalido(f"'{clave}': 'separador' debe ser un único carácter")
    if separador.isdigit() or separador == ".":
        raise PerfilInvalido(
            f"'{clave}': '{separador}' no sirve de separador (se confunde con el número)"
        )
    # Hoy solo se soportan campos de dos componentes (p. ej. SIS/DIA).
    if parte not in (0, 1):
        raise PerfilInvalido(f"'{clave}': 'parte' debe ser 0 o 1")
    return separador, parte
