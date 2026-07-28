# Módulo `ocr/` — lectura de signos vitales por OCR

Lee los signos vitales (FC, SpO2, FP, FR, Temp, PNI) de una **imagen fija** de la
pantalla de un monitor y produce el JSON del **contrato 1.1** con `origen: "ocr"` y
`confianza` real por signo. **Offline** — sin capturadora, sin MQTT, sin red.

Contexto y porqués: [`../DECISIONS.md`](../DECISIONS.md) (ADR-002, ADR-003, ADR-013,
ADR-014, ADR-015, **ADR-016**) · contrato: [`../docs/ito2/CONTRATO_DATOS.md`](../docs/ito2/CONTRATO_DATOS.md).

> **Dos motores, un mismo pipeline (ADR-016).**
> - **PaddleOCR** = motor de **producción**, lee monitores reales (frame de SimCore: 6/6
>   signos, 9/9 frames perturbados, 0 valores falsos). Dependencia **opcional**
>   (`ocr/requirements-motor.txt`).
> - **Plantilla 7-seg** = **andamiaje** sin dependencias: lee el mock sintético pero **no**
>   la tipografía real (ADR-014). Solo para tests y para el mock por CLI.
>
> Sin el motor de producción instalado, el motor por defecto **falla fuerte** (no lee en
> silencio). En cualquier caso la red de seguridad manda: ante una lectura dudosa, `null`,
> nunca un número inventado.

## Cómo correrlo

El andamiaje solo necesita `opencv-python` y `numpy` (ya en `requirements.txt`). El motor de
producción va aparte:

```bash
pip install -r ocr/requirements-motor.txt   # PaddleOCR (opcional; solo para leer real)
```

Desde la **raíz del repo**:

```bash
# Mock sintético con el andamiaje (no necesita el motor de producción)
python -m ocr.mock.generar_mock --salida monitor_mock.png
python -m ocr.cli --imagen monitor_mock.png --perfil ocr/perfiles/monitor_mock.json \
    --cama-id cama-01 --device-id jetson-01 --motor plantilla

# Frame real de SimCore con el motor de producción (requiere requirements-motor.txt)
python -m ocr.cli --imagen ocr/perfiles/simcore/frame_simcore.png \
    --perfil ocr/perfiles/simcore/simcore.json --cama-id cama-01 --device-id jetson-01
```

Para reproducir la comparativa de motores del ADR-016:

```bash
python -m ocr.herramientas.evaluar_motores
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

**Nunca se inventa un número.** Un signo sale `null` + `confianza: 0` si:

- el motor no lo reconoce, o informa confianza `< UMBRAL_CONFIANZA` (0.6, en `lector.py`);
- el motor informa una confianza fuera de [0, 1] (escala equivocada, `NaN`): se descarta la
  lectura, **no se recorta** el valor;
- el valor cae fuera del rango de plausibilidad del perfil;
- **la tinta toca el borde de la ROI**: el número puede estar cortado porque creció y ya no
  cabe en la caja calibrada, y un número truncado sigue pareciendo válido.

La PNI se emite completa o `null`, y además **coherente**: se exige `dia < sis` y
`dia ≤ media ≤ sis`. Una presión parcial o imposible (`40/75` con media 90, o una invertida
`75/120`) es clínicamente engañosa, y cada componente por separado pasa su propio rango
porque los rangos se solapan.

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
digitos.py      Render de dígitos 7 segmentos y '/' (compartido mock ↔ motor)
motor/base.py   Interfaz LectorOCR (motor intercambiable)
motor/paddle.py     Motor de PRODUCCIÓN (PaddleOCR); dependencia opcional (ADR-016)
motor/plantilla.py  Motor por plantilla — andamiaje, no apto para producción (ADR-014)
herramientas/calibrar.py        Calibrador de ROIs (overlay + tira de contacto)
herramientas/evaluar_motores.py Comparativa reproducible de motores (ADR-016)
perfiles/       Perfiles de monitor (JSON declarativo)
  monitor_mock.json         mock sintético (iteración 1)
  simcore/                  monitor real: frame de referencia + perfil
mock/           Generadores de imagen mock (completo y con PNI combinada)
tests/          pytest: mock, campos combinados, frame real, contrato, perfiles
```

## Añadir un perfil de monitor

Un perfil JSON describe dónde está cada signo en la pantalla de **un modelo** de monitor.
Los 8 signos del contrato son obligatorios (`fc, spo2, fp, fr, temp, pni_sis, pni_dia,
pni_media`), pero uno puede declararse **ausente**, y dos pueden compartir un **campo
combinado**:

```json
{
  "perfil": "umec12-v1",
  "resolucion": [1920, 1080],
  "signos": {
    "fc":  { "roi": [1690, 45, 225, 100], "tipo": "int", "unidad": "lpm", "rango": [20, 300] },
    "fp":  { "presente": false },
    "temp":{ "roi": [900, 652, 196, 84], "tipo": "float", "unidad": "C",
             "rango": [25.0, 45.0], "decimales": 1 },

    "pni_sis": { "roi": [10, 634, 305, 82], "tipo": "int", "unidad": "mmHg",
                 "rango": [30, 300], "separador": "/", "parte": 0 },
    "pni_dia": { "roi": [10, 634, 305, 82], "tipo": "int", "unidad": "mmHg",
                 "rango": [10, 200], "separador": "/", "parte": 1 },
    "pni_media": { "roi": [85, 716, 55, 32], "tipo": "int", "unidad": "mmHg",
                   "rango": [15, 250] }
  }
}
```

- `roi` en píxeles `[x, y, w, h]` de la imagen original; `unidad` debe coincidir con la del
  contrato (se valida); `tipo` es `int` o `float` (con `decimales` opcional); `rango` es de
  plausibilidad (ver arriba).
- **`"presente": false`** — el monitor no muestra ese signo. No lleva ROI y sale siempre
  `null` + confianza 0, sin gastar una pasada de OCR.
- **`"separador"` + `"parte"`** — campo combinado tipo `120/75`: los dos signos comparten
  ROI, se lee una sola vez y cada uno se queda con su mitad (`parte` 0 = izquierda,
  1 = derecha). Si el separador no aparece en el texto leído, **la PNI entera sale `null`**:
  interpretar `12075` como una presión sería inventar un dato.
- El perfil del mock **no se edita a mano**: se regenera con
  `python -m ocr.mock.generar_mock --perfil-salida ocr/perfiles/monitor_mock.json`
  (un test verifica que el archivo esté sincronizado con el generador).

### Calibrar las ROIs

**Calibra midiendo sobre un frame real, no a ojo.** La herramienta dibuja las cajas sobre el
frame y muestra cada recorte tal como lo ve el motor:

```bash
python -m ocr.herramientas.calibrar --frame ocr/perfiles/simcore/frame_simcore.png \
    --perfil ocr/perfiles/simcore/simcore.json --salida-dir /tmp/calib --detalle
```

Produce `overlay.png` (cajas sobre el frame) y `rois.png` (tira de contacto binarizada), más
una tabla con lo leído. Con `--detalle`, el mejor y el segundo candidato por glifo: si el
margen entre ambos es pequeño, el reconocimiento fue azar aunque la confianza parezca buena.

Cada caja debe encuadrar **solo el número**: las etiquetas y unidades vecinas (`bpm`, `%`,
`/min`, `°C`, `MAP`) tienen que quedar fuera. Ojo con las unidades que contienen `/`, porque
se confundirían con el separador de un campo combinado. Ten en cuenta también hacia dónde
crece el valor al ganar un dígito: con texto alineado a la izquierda y la unidad pegada a la
derecha, una ROI fija puede no dar de sí (limitación documentada en ADR-015).

## Cambiar de motor OCR

El motor es intercambiable (ADR-013). Desde la iteración 3 (ADR-016) el lector entrega al
motor el **recorte crudo** (color) de la ROI; cada motor preprocesa a su gusto. Para enchufar
otro:

```python
from ocr.motor.base import LectorOCR

class MiMotor(LectorOCR):
    def leer(self, imagen):          # imagen: recorte BGR crudo de la ROI
        ...
        return texto, confianza      # ('0'-'9', '.', '/'; confianza 0–1) o (None, 0.0)

mensaje = leer_imagen(..., motor=MiMotor())
```

El resto del módulo (perfiles, preproceso, validación, contrato, partición de campos
combinados) no cambia, y las salvaguardas viven en el lector, *delante* del motor. Devuelve la
confianza en [0, 1]; `_confianza_valida` es la última red, no el primer filtro. No recortes
caracteres no numéricos del texto: si el modelo leyó una letra, deja que el lector lo rechace
entero (mejor `null` que un número truncado inventado).

## Camino a la Jetson (documentado, no implementado — ADR-016)

- **Recomendado:** exportar el modelo rec de PaddleOCR a **ONNX** (`paddle2onnx`) y correrlo
  con `onnxruntime-gpu` (TensorRT/CUDA) en el Orin Nano. Más ligero que instalar
  `paddlepaddle` en el edge. **Pendiente:** la paridad ONNX↔modelo no se pudo verificar en el
  dev de Windows (`paddle2onnx` falla al cargar su DLL ahí; funciona en Linux/aarch64) — se
  valida en el target Jetson.
- **Fallbacks:** `paddlepaddle` directo con wheels aarch64; o EasyOCR (PyTorch para Jetson).
- **Offline (sin internet):** pre-descargar y empaquetar el modelo; para el edge, el modelo
  **mobile** en vez del `medium` del dev.

## Fuera de alcance de esta iteración

Capturadora/V4L2, MQTT, video/RTSP, multi-cama concurrente y despliegue físico en la Jetson.
Ver el estado general en [`../CONTEXT.md`](../CONTEXT.md) §5.
