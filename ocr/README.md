# Módulo `ocr/` — lectura de signos vitales por OCR

Lee los signos vitales (FC, SpO2, FP, FR, Temp, PNI) de una **imagen fija** de la
pantalla de un monitor y produce el JSON del **contrato 1.1** con `origen: "ocr"` y
`confianza` real por signo. **Offline** — sin capturadora, sin MQTT, sin red.

Contexto y porqués: [`../DECISIONS.md`](../DECISIONS.md) (ADR-002, ADR-003, ADR-013,
ADR-014, ADR-015, ADR-016, **ADR-017**) · contrato: [`../docs/ito2/CONTRATO_DATOS.md`](../docs/ito2/CONTRATO_DATOS.md).

> **Dos motores, un mismo pipeline (ADR-017).**
> - **RapidOCR/ONNX Runtime** = motor de **producción**: mismos modelos PP-OCR, backend
>   `onnxruntime` — estable en la Jetson aarch64 (Paddle Inference segfaultea ahí, ADR-017),
>   lee ambos frames de referencia (6/6 signos, 9/9 frames perturbados, 0 valores falsos,
>   ~88 ms/frame en CPU) y trae los modelos **dentro del wheel** (offline de fábrica).
>   Dependencia **opcional** (`ocr/requirements-motor.txt`).
> - **Plantilla 7-seg** = **andamiaje** sin dependencias: lee el mock sintético pero **no**
>   la tipografía real (ADR-014). Solo para tests y para el mock por CLI.
> - (PaddleOCR queda como adaptador **alternativo** en x86_64 — `ocr/motor/paddle.py` —
>   sin declarar en requirements; se usa por API con `motor=LectorPaddleOCR()`.)
>
> Sin el motor de producción instalado, el motor por defecto **falla fuerte** (no lee en
> silencio). En cualquier caso la red de seguridad manda: ante una lectura dudosa, `null`,
> nunca un número inventado.

## Cómo correrlo

El runtime mínimo de `ocr/` está en [`requirements.txt`](requirements.txt) (opencv, numpy,
paho-mqtt — sin las dependencias de otros módulos del repo). El motor de producción va aparte:

```bash
pip install -r ocr/requirements.txt         # runtime del módulo (autocontenido)
pip install -r ocr/requirements-motor.txt   # RapidOCR/onnxruntime (para leer monitores reales)
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

Como librería (lo que usa el publicador y usará el pipeline en vivo):

```python
from ocr.lector import leer_imagen

mensaje = leer_imagen("captura.png", "ocr/perfiles/monitor_mock.json",
                      cama_id="cama-01", device_id="jetson-01")
```

Tests:

```bash
python -m pytest ocr/tests -q
```

## Publicar por MQTT (puente OCR → dashboard)

`python -m ocr.publicar` lee un frame en bucle, lo pasa por `leer_imagen()` y publica el
contrato por MQTT al Mosquitto del servidor, de modo que la cama aparezca en el **dashboard
web existente** — el mismo camino que el `simulador/`. Solo transporta lo que el OCR ya
validó (los `null` se publican como `null`; la web los muestra como "--").

```bash
# Producción: RapidOCR lee el frame de SimCore y lo publica (requiere el motor y Mosquitto)
python -m ocr.publicar --broker 100.110.157.112 --cama-id cama-01

# Solo transporte, sin el motor real: valida MQTT/estado/web (los valores van null)
python -m ocr.publicar --broker 100.110.157.112 --cama-id cama-01 --motor plantilla

# Sin broker, imprime el JSON en consola (prueba rápida)
python -m ocr.publicar --motor plantilla --solo-consola
```

Flags: `--broker` (def. `100.110.157.112`, o env `MQTT_BROKER`), `--puerto-broker` (1883),
`--cama-id` (`cama-01`), `--device-id` (`jetson-01`), `--hz` (1.0), `--imagen`/`--perfil`
(def. el frame y perfil de SimCore), `--motor {produccion,plantilla}`, `--solo-consola`.
Publica `monitoreo/vitales/{cama_id}` y `monitoreo/estado/{cama_id}` (QoS 1, retained); al
arrancar marca la cama `online`, y al salir (Ctrl+C) `offline`.

**Verlo en el dashboard.** En el servidor, `mosquitto_sub -h localhost -t 'monitoreo/#' -v`
muestra los mensajes; en el navegador, la cama aparece en el grid (el video mostrará "sin
cámara" — es otro camino). **No corras el simulador sobre la misma `cama_id`**: ambos
publican al mismo topic retenido y se pisarían; usa una cama dedicada para el OCR.

> Si el proceso se mata en duro (`kill -9`) no se envía `offline`; la web marca la cama
> desconectada igual por su timeout de datos (`TIMEOUT_DATOS_MS`, 5 s).

## Captura en vivo (capturadora HDMI→USB)

El bucle pide frames a una `FuenteFrames` (`ocr/fuente.py`). Con `--fuente capturadora`,
la `FuenteCapturadora` lee el dispositivo V4L2 en vivo (MJPG 1920×1080), descarta los
~15 frames negros de arranque y valida que la resolución coincida con la del perfil:

```bash
python -m ocr.publicar --fuente capturadora --dispositivo /dev/video0 \
    --broker 100.110.157.112 --cama-id cama-09
```

Política de seguridad ante fallo de lectura: reintenta unas pocas veces y luego **lanza**
(el `finally` publica `offline` y el proceso termina con error). **Nunca sirve un frame
viejo**: republicar un frame congelado con `ts` fresco sería presentar datos viejos como
actuales — el mismo pecado que inventar un número. La web muestra la cama desconectada,
que es la verdad.

Esa regla cubre también el buffering del driver: la cola V4L2 se fija a **1 frame**
(`CAP_PROP_BUFFERSIZE`) y cada lectura se drena con `grab()` antes del `read()` servido —
sin eso, OpenCV entrega el frame **más viejo** de una cola de 4 (a 1 Hz, ~4 s de retraso
publicados como actuales, y una desconexión tardaría ~4 ticks en notarse).

El perfil `simcore.json` está **calibrado contra el frame real de la capturadora**
(`frame_capturadora.png`) y verificado también sobre el screenshot (`frame_simcore.png`):
el mismo perfil lee ambos (test de aceptación parametrizado; FC 73 en la capturadora, 74
en el screenshot — son capturas de momentos distintos).

### Runbook: desplegar en la Jetson

1. **Clonar el repo** en la Jetson (`jetson@…`, JetPack 6 / L4T r36, aarch64).
2. **Entorno aislado con Python 3.10** — el `base` de conda es 3.13 y **no tocar el entorno
   de ROS** que vive en esa Jetson:
   ```bash
   conda create -n ocr-monitoreo python=3.10 -y
   conda activate ocr-monitoreo
   pip install -r ocr/requirements.txt
   pip install -r ocr/requirements-motor.txt
   ```
   El motor es **RapidOCR sobre ONNX Runtime** (ADR-017): `onnxruntime` corre estable en
   aarch64 (par validado en esta placa: rapidocr 1.4.4 + onnxruntime 1.22.1). No instalar
   `paddlepaddle` — su motor de inferencia segfaultea en la Orin.
3. **Sin pre-descarga de modelos**: el wheel de `rapidocr-onnxruntime` trae los `.onnx`
   empaquetados (det+rec+cls, ~16 MB), así que funciona **sin internet** desde el primer
   arranque. No hay carpeta que pre-sembrar ni variables de entorno que fijar.
4. **La fuente de video debe estar activa**: la Mac en **modo espejo** (o SimCore en el
   monitor externo) — si no, la capturadora entrega negro y todos los signos salen `null`
   (comportamiento correcto: no hay nada que leer).
5. **Correr y verificar**: el comando de arriba; en el servidor
   `mosquitto_sub -h localhost -t 'monitoreo/#' -v` y la cama en el dashboard, cambiando
   en vivo con SimCore.
6. Límite conocido (ADR-015): si un valor crece a más dígitos de los que su ROI admite,
   toca el borde y sale `null` (nunca un dato falso truncado). Con captura en vivo esto
   puede verse como `null` intermitente en valores extremos.

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
cli.py          Lee una imagen y emite el JSON (python -m ocr.cli)
publicar.py     Puente OCR → MQTT en bucle (python -m ocr.publicar)
publicador.py   PublicadorOCR: transporta el contrato por MQTT (cliente inyectado)
fuente.py       FuenteFrames + FuenteImagenFija + FuenteCapturadora (V4L2 en vivo)
tiempo.py       ahora_iso(): marca de tiempo del contrato (compartida lector/publicador)
contrato.py     Construcción del JSON 1.1 (unidades fijas, PNI todo-o-nada)
perfiles.py     Carga y validación de perfiles de ROI
preproceso.py   Recorte de ROI, gris, umbral Otsu, normalización
digitos.py      Render de dígitos 7 segmentos y '/' (compartido mock ↔ motor)
motor/base.py   Interfaz LectorOCR (motor intercambiable)
motor/rapid.py      Motor de PRODUCCIÓN (RapidOCR/onnxruntime); dep. opcional (ADR-017)
motor/paddle.py     Motor alternativo x86_64 (histórico ADR-016; segfaultea en aarch64)
motor/plantilla.py  Motor por plantilla — andamiaje, no apto para producción (ADR-014)
herramientas/calibrar.py        Calibrador de ROIs (overlay + tira de contacto)
herramientas/evaluar_motores.py Comparativa reproducible de motores (ADR-016)
perfiles/       Perfiles de monitor (JSON declarativo)
  monitor_mock.json         mock sintético (iteración 1)
  simcore/                  perfil + 2 frames de referencia (screenshot y capturadora)
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

## El motor en la Jetson (ADR-017)

La vía ONNX que ADR-016 dejó anotada resultó ser **el camino de producción**, y ya está
integrada: `rapidocr-onnxruntime` ejecuta los modelos PP-OCR con `onnxruntime`
(CPUExecutionProvider), estable en aarch64 donde Paddle Inference segfaultea. Los modelos
vienen dentro del wheel — sin descargas en runtime. Seguimiento pendiente: medir ms/frame
en la Orin (a 1 Hz rec-only sobra de lejos: 88 ms/frame en CPU x86); si algún día hiciera
falta, el ExecutionProvider de GPU/TensorRT es la palanca.

## Fuera de alcance de esta iteración

Multi-cama, alarmas, caja negra, respiración por IA.
Ver el estado general en [`../CONTEXT.md`](../CONTEXT.md) §5.
