"""Carga y validación de perfiles de monitor (ROIs por signo).

Un perfil es un JSON declarativo que describe, para un modelo de monitor, la
caja [x, y, w, h] donde aparece cada signo, su tipo de dato, unidad y rango de
plausibilidad. Los ROIs se definen a mano por modelo (ADR-002: cambiar de
monitor exige reajustar regiones).

Nota sobre `rango`: es un rango de PLAUSIBILIDAD FISIOLÓGICA (amplio), pensado
para descartar basura del OCR (p. ej. una FC de 999 por lectura fantasma).
NO es el "rango neonatal típico" del contrato, que es descriptivo: un valor
anormal pero real (p. ej. bradicardia de 80 lpm) debe mostrarse, no ocultarse.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from ocr.contrato import UNIDADES_CONTRATO

TIPOS_VALIDOS = ("int", "float")


class PerfilInvalido(ValueError):
    """El archivo de perfil no cumple el esquema esperado."""


@dataclass(frozen=True)
class SignoPerfil:
    roi: tuple            # (x, y, w, h) en píxeles de la imagen original
    tipo: str             # "int" | "float"
    unidad: str           # fija por contrato (se valida contra UNIDADES_CONTRATO)
    rango: tuple          # (mínimo, máximo) de plausibilidad fisiológica
    decimales: int = 0    # decimales esperados (solo informativo para float)


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

    return Perfil(nombre=nombre, resolucion=(ancho_img, alto_img), signos=signos)


def _validar_signo(clave: str, cfg: dict, ancho_img: int, alto_img: int) -> SignoPerfil:
    if not isinstance(cfg, dict):
        raise PerfilInvalido(f"'{clave}': debe ser un objeto")

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

    unidad = cfg.get("unidad")
    if unidad != UNIDADES_CONTRATO[clave]:
        raise PerfilInvalido(
            f"'{clave}': unidad '{unidad}' no coincide con la del contrato "
            f"('{UNIDADES_CONTRATO[clave]}'); las unidades son fijas por contrato"
        )

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

    return SignoPerfil(
        roi=(x, y, w, h),
        tipo=tipo,
        unidad=unidad,
        rango=(rango[0], rango[1]),
        decimales=decimales,
    )
