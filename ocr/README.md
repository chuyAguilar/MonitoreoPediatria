# Módulo `ocr/` — lectura de signos vitales por OCR

Lee los signos vitales (FC, SpO2, FP, FR, Temp, PNI) de una **imagen fija** de la
pantalla de un monitor y produce el JSON del **contrato 1.1** con `origen: "ocr"` y
`confianza` real por signo. Iteración 1: **offline** — sin capturadora, sin MQTT, sin red.

Contexto y porqués: [`../DECISIONS.md`](../DECISIONS.md) (ADR-002, ADR-003, ADR-013,
**ADR-014**, **ADR-015**) · contrato: [`../docs/ito2/CONTRATO_DATOS.md`](../docs/ito2/CONTRATO_DATOS.md).

> **Estado del motor OCR.** El motor incluido (plantilla de 7 segmentos) es **andamiaje de
> desarrollo**: lee la imagen mock, pero **no lee la tipografía de un monitor real** (5 de 17
> dígitos sobre el frame de SimCore). El motor de producción está por decidir — ver ADR-014.
> Lo que sí está probado sobre datos reales es la red de seguridad: con lecturas erróneas en
> la entrada, el módulo no publicó ni un valor equivocado; todo salió `null`.

## Cómo correrlo

Desde la **raíz del repo** (necesita `opencv-python` y `numpy`, ya en `requirements.txt`):

```bash
# 1. Generar la imagen mock del monitor (valores conocidos)
python -m ocr.mock.generar_mock --salida monitor_mock.png

# 2. Leerla y emitir el contrato 1.1 por consola
python -m ocr.cli --imagen monitor_mock.png --perfil ocr/perfiles/monitor_mock.json \
    --cama-id cama-01 --device-id jetson-01

# Sobre el frame real de SimCore (hoy devuelve todo null, ver ADR-014)
python -m ocr.cli --imagen ocr/perfiles/simcore/frame_simcore.png \
    --perfil ocr/perfiles/simcore/simcore.json --cama-id cama-01 --device-id jetson-01
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
motor/plantilla.py  Motor por plantilla — andamiaje, no apto para producción (ADR-014)
herramientas/calibrar.py  Calibrador de ROIs (overlay + tira de contacto)
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

El motor es intercambiable (ADR-013). `motor/plantilla.py` es **andamiaje**: ADR-014 midió
que no lee tipografía real, así que el motor de producción está por decidir (candidato
principal: PaddleOCR sobre la GPU de la Jetson). Para enchufar otro:

```python
from ocr.motor.base import LectorOCR

class LectorPaddle(LectorOCR):
    def leer(self, imagen):          # imagen: ROI binaria (dígitos blancos / fondo negro)
        ...
        return texto, confianza      # ('0'-'9' y '.', 0-1) o (None, 0.0)

mensaje = leer_imagen(..., motor=LectorPaddle())
```

El resto del módulo (perfiles, preproceso, validación, contrato, partición de campos
combinados) no cambia. Cuando el motor nuevo lea el frame real, el test de aceptación
`test_aceptacion_lee_el_frame_real` pasará y su `xfail(strict=True)` obligará a retirarlo.

## Fuera de alcance de esta iteración

Capturadora/V4L2, MQTT, video/RTSP, multi-cama concurrente y optimización Jetson.
Ver el estado general en [`../CONTEXT.md`](../CONTEXT.md) §5.
