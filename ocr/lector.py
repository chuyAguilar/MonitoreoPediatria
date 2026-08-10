"""Orquestador del OCR: imagen + perfil → mensaje del contrato 1.1.

Uso como librería (lo que usará el pipeline en vivo de la siguiente iteración):

    from ocr.lector import leer_imagen
    mensaje = leer_imagen("captura.png", "ocr/perfiles/monitor_mock.json",
                          cama_id="cama-01", device_id="jetson-01")

Reglas de robustez (brief §4.5, CONTEXT.md §1): valor no reconocido, con
confianza baja o fuera del rango de plausibilidad → null + confianza 0.
Nunca se inventa un número.
"""

from pathlib import Path

import cv2
import numpy as np

from ocr import contrato, preproceso
from ocr.motor.base import LectorOCR
from ocr.perfiles import Perfil, cargar_perfil
from ocr.tiempo import ahora_iso

# Confianza mínima del motor para aceptar una lectura
UMBRAL_CONFIANZA = 0.6


def motor_por_defecto() -> LectorOCR:
    """Devuelve el motor de PRODUCCIÓN, o falla fuerte si no está instalado.

    Producción = RapidOCR sobre ONNX Runtime (ADR-017; Paddle Inference
    segfaultea en la Jetson aarch64). Falla fuerte a propósito (no cae al
    andamiaje de plantilla): un sistema de monitoreo que silenciosamente no
    lee nada es peor que uno que se niega a arrancar y dice por qué. El motor
    de plantilla NO lee monitores reales (ADR-014); solo sirve para tests y
    se usa pasándolo explícito con `motor=`.
    """
    try:
        # LectorRapidOCR importa rapidocr_onnxruntime de forma perezosa en su
        # __init__, así que el ImportError aparece al instanciar, no al
        # importar: la instanciación va dentro del try a propósito.
        from ocr.motor.rapid import LectorRapidOCR
        return LectorRapidOCR()
    except ImportError as e:
        raise RuntimeError(
            "Motor de producción (RapidOCR/onnxruntime) no instalado: el "
            "módulo OCR no puede leer monitores reales. Instala con "
            "`pip install -r ocr/requirements-motor.txt`, o pasa un motor "
            "explícito con motor= (el de plantilla es solo andamiaje de test "
            "y NO lee monitores reales)."
        ) from e


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
        motor = motor_por_defecto()
    if ts is None:
        ts = ahora_iso()

    lecturas = {}
    # Caché por ROI: dos signos pueden compartir el mismo recorte (p. ej. la
    # sistólica y la diastólica de un campo "120/75"). Además de ahorrar una
    # pasada de OCR, garantiza que ambos componentes salgan de la MISMA lectura.
    cache_roi = {}
    for nombre, cfg in perfil.signos.items():
        if not cfg.presente:
            # El monitor no muestra este signo: null sin intentar leer píxeles.
            lecturas[nombre] = (None, 0.0)
            continue

        if cfg.roi not in cache_roi:
            recorte = preproceso.recortar_roi(imagen, cfg.roi)
            # La binaria es solo para las guardas del lector (borde/contraste);
            # al motor se le entrega el recorte CRUDO y él preprocesa a su gusto
            # (los motores reales rinden mucho peor sobre la binaria). ADR-016.
            binaria = preproceso.binarizar(recorte)
            if preproceso.tinta_en_el_borde(binaria):
                # El número toca el borde de su caja: puede estar cortado y no
                # hay forma de saber qué falta. Se descarta entero.
                cache_roi[cfg.roi] = (None, 0.0)
            else:
                cache_roi[cfg.roi] = motor.leer(recorte)
        texto, confianza = cache_roi[cfg.roi]
        confianza = _confianza_valida(confianza)

        if cfg.separador is not None:
            texto = _extraer_parte(texto, cfg.separador, cfg.parte)

        valor = _interpretar(texto, cfg.tipo)
        if (
            valor is None
            or confianza is None
            or confianza < umbral_confianza
            or not (cfg.rango[0] <= valor <= cfg.rango[1])
        ):
            lecturas[nombre] = (None, 0.0)
        else:
            lecturas[nombre] = (valor, round(float(confianza), 3))

    return contrato.construir_mensaje(cama_id, device_id, ts, lecturas)


def _confianza_valida(confianza):
    """Normaliza la confianza del motor; None si incumple la interfaz.

    `LectorOCR` documenta confianza en [0, 1], pero el motor es intercambiable y
    un adaptador mal cableado podría devolver otra escala (Tesseract expone 0–100)
    o un NaN. Como el umbral se aplica con `confianza < umbral`, una escala 0–100
    dejaría pasar TODAS las lecturas y un NaN también (toda comparación con NaN es
    falsa): la puerta de seguridad quedaría desactivada en silencio.

    Deliberadamente **no se recorta al rango**: convertir un 7.5 en 1.0 haría
    pasar por óptima la peor lectura posible. Fuera de dominio se descarta.
    """
    # `bool` es subclase de `int`: sin esta guarda, un True colaría como 1.0,
    # es decir como la lectura más confiable posible.
    if isinstance(confianza, bool) or not isinstance(confianza, (int, float)):
        return None
    valor = float(confianza)
    # La comparación también descarta NaN, que es falsa contra cualquier cosa.
    if not 0.0 <= valor <= 1.0:
        return None
    return valor


def _extraer_parte(texto, separador: str, parte: int):
    """Parte el texto de un campo combinado y devuelve el componente pedido.

    Exige exactamente dos componentes (p. ej. "120/75"). Si el separador no
    aparece —porque el motor no lo reconoció— el texto se descarta entero: leer
    "12075" como si fuera una presión sería justo el tipo de número inventado
    que el módulo no debe producir.
    """
    if not texto:
        return None
    partes = texto.split(separador)
    if len(partes) != 2:
        return None
    return partes[parte]


def _interpretar(texto, tipo: str):
    """Convierte el texto del motor al tipo del signo; None si no es un número válido.

    Nunca lanza: un texto no convertible (incluidos dígitos Unicode raros como
    "7²", que pasan `str.isdigit()` pero rompen `int()`) degrada ese signo a
    None, no tumba el frame entero. La interfaz LectorOCR exige que el fallo sea
    (None, 0.0), no una excepción (ver ocr/motor/base.py).
    """
    if not texto:
        return None
    try:
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
    except ValueError:
        return None
