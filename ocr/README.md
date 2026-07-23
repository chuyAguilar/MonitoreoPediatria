# Módulo `ocr/` — lectura de signos vitales por OCR

Lee los signos vitales (FC, SpO2, FP, FR, Temp, PNI) de una **imagen fija** de la
pantalla de un monitor y produce el JSON del **contrato 1.1** con `origen: "ocr"` y
`confianza` real por signo. Iteración 1: **offline** — sin capturadora, sin MQTT, sin red.

Contexto y porqués: [`../DECISIONS.md`](../DECISIONS.md) (ADR-002, ADR-003, **ADR-013**) ·
contrato: [`../docs/ito2/CONTRATO_DATOS.md`](../docs/ito2/CONTRATO_DATOS.md).

## Cómo correrlo

Desde la **raíz del repo** (necesita `opencv-python` y `numpy`, ya en `requirements.txt`):

```bash
# 1. Generar la imagen mock del monitor (valores conocidos)
python -m ocr.mock.generar_mock --salida monitor_mock.png

# 2. Leerla y emitir el contrato 1.1 por consola
python -m ocr.cli --imagen monitor_mock.png --perfil ocr/perfiles/monitor_mock.json \
    --cama-id cama-01 --device-id jetson-01
```

Como librería (lo que usará el pipeline en vivo):

```python
from ocr.lector import leer_imagen

mensaje = leer_imagen("captura.png", "ocr/perfiles/monitor_mock.json",
                      cama_id="cama-01", device_id="jetson-01")
```

Tests:

```bash
python -m pytest ocr/tests -q
```

## Reglas de robustez

Valor no reconocido, con confianza `< UMBRAL_CONFIANZA` (0.6, en `lector.py`) o fuera del
rango de plausibilidad del perfil → `valor: null` + `confianza: 0`. **Nunca se inventa un
número.** La PNI se emite completa (sis/dia/media) o `null`: una tensión parcial es
clínicamente engañosa.

Los `rango` del perfil son de **plausibilidad fisiológica** (amplios, filtran basura del
OCR como una FC de 999). NO son los "rangos neonatales típicos" del contrato, que son
descriptivos: un valor anormal pero real (bradicardia de 80 lpm) debe mostrarse.

## Estructura

```
lector.py       Orquestador: imagen + perfil → mensaje contrato 1.1
cli.py          Entrada por consola (python -m ocr.cli)
contrato.py     Construcción del JSON 1.1 (unidades fijas, PNI todo-o-nada)
perfiles.py     Carga y validación de perfiles de ROI
preproceso.py   Recorte de ROI, gris, umbral Otsu, normalización
digitos.py      Render de dígitos 7 segmentos (compartido mock ↔ motor)
motor/base.py   Interfaz LectorOCR (motor intercambiable)
motor/plantilla.py  Motor por plantilla — andamiaje de la iteración 1
perfiles/       Perfiles de monitor (JSON declarativo)
mock/           Generador de la imagen mock + perfil derivado
tests/          pytest contra el mock (E2E, rangos, contrato, perfiles)
```

## Añadir un perfil de monitor

Un perfil JSON describe dónde está cada signo en la pantalla de **un modelo** de monitor:

```json
{
  "perfil": "umec10-v1",
  "resolucion": [1920, 1080],
  "signos": {
    "fc": { "roi": [x, y, w, h], "tipo": "int", "unidad": "lpm", "rango": [50, 250] },
    "...": "los 8 signos son obligatorios: fc, spo2, fp, fr, temp, pni_sis, pni_dia, pni_media"
  }
}
```

- `roi` en píxeles de la imagen original; `unidad` debe coincidir con la del contrato
  (se valida); `tipo` es `int` o `float` (con `decimales` opcional); `rango` es de
  plausibilidad (ver arriba).
- El perfil del mock **no se edita a mano**: se regenera con
  `python -m ocr.mock.generar_mock --perfil-salida ocr/perfiles/monitor_mock.json`
  (un test verifica que el archivo esté sincronizado con el generador).

## Cambiar de motor OCR

El motor es intercambiable (ADR-013). `motor/plantilla.py` es **andamiaje de la
iteración 1**; el motor de producción se decidirá con la muestra real del monitor
(candidato principal: PaddleOCR sobre la GPU de la Jetson). Para enchufar otro:

```python
from ocr.motor.base import LectorOCR

class LectorPaddle(LectorOCR):
    def leer(self, imagen):          # imagen: ROI binaria (dígitos blancos / fondo negro)
        ...
        return texto, confianza      # ('0'-'9' y '.', 0-1) o (None, 0.0)

mensaje = leer_imagen(..., motor=LectorPaddle())
```

El resto del módulo (perfiles, preproceso, validación, contrato) no cambia.

## Fuera de alcance de esta iteración

Capturadora/V4L2, MQTT, video/RTSP, multi-cama concurrente y optimización Jetson.
Ver el estado general en [`../CONTEXT.md`](../CONTEXT.md) §5.
