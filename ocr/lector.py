"""Orquestador del OCR: imagen + perfil → mensaje del contrato 1.1.

Uso como librería (lo que usará el pipeline en vivo de la siguiente iteración):

    from ocr.lector import leer_imagen
    mensaje = leer_imagen("captura.png", "ocr/perfiles/monitor_mock.json",
                          cama_id="cama-01", device_id="jetson-01")

Reglas de robustez (brief §4.5, CONTEXT.md §1): valor no reconocido, con
confianza baja o fuera del rango de plausibilidad → null + confianza 0.
Nunca se inventa un número.
"""

from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from ocr import contrato, preproceso
from ocr.motor.base import LectorOCR
from ocr.motor.plantilla import LectorPlantilla
from ocr.perfiles import Perfil, cargar_perfil

# Confianza mínima del motor para aceptar una lectura
UMBRAL_CONFIANZA = 0.6


def leer_imagen(
    imagen,
    perfil,
    cama_id: str,
    device_id: str,
    motor: LectorOCR = None,
    ts: str = None,
    umbral_confianza: float = UMBRAL_CONFIANZA,
) -> dict:
    """Lee todos los signos de una imagen fija y devuelve el mensaje 1.1.

    `imagen`: ruta a PNG/JPG o arreglo BGR ya cargado.
    `perfil`: ruta al JSON del perfil o un Perfil ya cargado.
    """
    if isinstance(imagen, (str, Path)):
        ruta = str(imagen)
        imagen = cv2.imread(ruta, cv2.IMREAD_COLOR)
        if imagen is None:
            raise ValueError(f"No se pudo leer la imagen: {ruta}")
    if not isinstance(imagen, np.ndarray):
        raise TypeError("'imagen' debe ser una ruta o un arreglo numpy")

    if isinstance(perfil, (str, Path)):
        perfil = cargar_perfil(perfil)
    if not isinstance(perfil, Perfil):
        raise TypeError("'perfil' debe ser una ruta o un ocr.perfiles.Perfil")

    alto_img, ancho_img = imagen.shape[:2]
    if (ancho_img, alto_img) != perfil.resolucion:
        raise ValueError(
            f"La imagen es {ancho_img}x{alto_img} pero el perfil '{perfil.nombre}' "
            f"describe {perfil.resolucion[0]}x{perfil.resolucion[1]}"
        )

    if motor is None:
        motor = LectorPlantilla()
    if ts is None:
        ts = _ahora_iso()

    lecturas = {}
    for nombre, cfg in perfil.signos.items():
        recorte = preproceso.recortar_roi(imagen, cfg.roi)
        binaria = preproceso.binarizar(recorte)
        texto, confianza = motor.leer(binaria)
        valor = _interpretar(texto, cfg.tipo)
        if (
            valor is None
            or confianza < umbral_confianza
            or not (cfg.rango[0] <= valor <= cfg.rango[1])
        ):
            lecturas[nombre] = (None, 0.0)
        else:
            lecturas[nombre] = (valor, round(float(confianza), 3))

    return contrato.construir_mensaje(cama_id, device_id, ts, lecturas)


def _interpretar(texto, tipo: str):
    """Convierte el texto del motor al tipo del signo; None si no es un número válido."""
    if not texto:
        return None
    if tipo == "int":
        return int(texto) if texto.isdigit() else None
    # float: dígitos con a lo sumo un punto, ni al inicio ni al final
    if (
        texto.count(".") > 1
        or texto.startswith(".")
        or texto.endswith(".")
        or not texto.replace(".", "").isdigit()
    ):
        return None
    return float(texto)


def _ahora_iso() -> str:
    """Fecha/hora UTC ISO-8601 con sufijo Z (mismo formato que el simulador)."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
