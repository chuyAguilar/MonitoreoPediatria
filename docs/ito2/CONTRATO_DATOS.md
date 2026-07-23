# Contrato de datos — signos vitales (Hito 2)

Especificación del formato con el que viajan los signos vitales desde el edge hasta la web. Es un **contrato**: la web se construye contra él y la fuente es intercambiable (ver `DECISIONS.md` ADR-001). Versión vigente: **`1.1`** (ver §6).

- **Pipeline OCR** (paradigma actual, módulo `ocr/`): lee la pantalla del monitor y produce este formato con `origen: "ocr"` y `confianza` por signo.
- **Simulador** (banco de pruebas): produce **exactamente el mismo formato**; sirve para probar la web sin hardware.
- Un adaptador digital del monitor (HL7/PDS) seguiría siendo una fuente válida del mismo contrato si algún monitor lo permite (ADR-012).

> Sin IA en esta etapa. Solo capturar/simular datos, transmitirlos junto al video y mostrarlos.

## 1. Identificación (clave para multi-cama)

Cada cama tiene un identificador único que amarra sus datos con su video.

| Campo | Qué es | Ejemplo |
|-------|--------|---------|
| `cama_id` | Identificador de la cama/paciente monitorizado | `cama-01` |
| `device_id` | Edge (Raspberry/PC) que capturó el dato | `edge-01` |

Convención: `cama-NN` (dos dígitos), `edge-NN`. El `cama_id` es **el mismo** que el nombre del stream de video en el servidor (ver sección 5), para que la web una video + datos.

## 2. Transporte — MQTT

Las vitales viajan por **MQTT** (broker Mosquitto en el servidor). Encaja con muchos edges publicando a la vez.

| Tema (topic) | Publica | Contenido | QoS / retención |
|--------------|---------|-----------|------------------|
| `monitoreo/vitales/{cama_id}` | edge | JSON de numéricos (~1 Hz) | QoS 1, retained |
| `monitoreo/estado/{cama_id}` | edge | online/offline, batería del edge, etc. | QoS 1, retained |

- **retained**: el broker guarda el último mensaje, así la web muestra valores apenas se conecta.
- La web se suscribe a `monitoreo/vitales/+` para recibir **todas** las camas, o a una sola para el detalle.
- La web habla MQTT sobre WebSocket (Mosquitto lo expone en otro puerto).

## 3. Mensaje de numéricos (JSON)

Tema `monitoreo/vitales/{cama_id}`, ~1 vez por segundo:

```json
{
  "contrato": "1.1",
  "cama_id": "cama-01",
  "device_id": "jetson-01",
  "ts": "2026-07-22T20:15:03Z",
  "origen": "ocr",
  "signos": {
    "fc":   { "valor": 142,  "unidad": "lpm", "confianza": 0.98 },
    "spo2": { "valor": 97,   "unidad": "%",   "confianza": 0.95 },
    "fp":   { "valor": 141,  "unidad": "lpm", "confianza": 0.9 },
    "fr":   { "valor": 48,   "unidad": "rpm", "confianza": 0.88 },
    "temp": { "valor": 36.9, "unidad": "C",   "confianza": 0.97 },
    "pni":  { "sis": 66, "dia": 39, "media": 48, "unidad": "mmHg", "ts": "2026-07-22T20:10:00Z", "confianza": 0.8 }
  }
}
```

### Campos de cabecera
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `contrato` | string | Versión del contrato (`"1.1"`, ver §6) |
| `cama_id` | string | Cama de origen |
| `device_id` | string | Edge de origen |
| `ts` | string | Fecha/hora UTC ISO-8601 del muestreo |
| `origen` | string | `"simulador"`, `"umec10"` u `"ocr"` (de dónde salió el dato) |

### Signos vitales (objeto `signos`)
| Clave | Significado | Unidad | Rango neonatal típico |
|-------|-------------|--------|------------------------|
| `fc` | Frecuencia cardiaca (ECG) | lpm | 120–160 |
| `spo2` | Saturación de oxígeno | % | 90–100 |
| `fp` | Frecuencia de pulso (oxímetro) | lpm | 120–160 |
| `fr` | Frecuencia respiratoria (impedancia) | rpm | 40–60 |
| `temp` | Temperatura | °C | 36.5–37.5 |
| `pni` | Presión no invasiva (sis/dia/media) | mmHg | ~65/40, media ~50 |

> **Nota sobre el "rango neonatal típico":** esta columna es **descriptiva** (qué valores
> son normales en un neonato); **no** es un rango de validación. El pipeline OCR valida con
> rangos de **plausibilidad fisiológica** más amplios, definidos en su perfil, cuyo único
> fin es descartar lecturas basura del OCR sin ocultar valores anormales pero reales
> (p. ej. una bradicardia de 80 lpm debe mostrarse). Ver `DECISIONS.md` ADR-013.

Reglas:
- Si un sensor no está conectado, su valor es `null` (la web lo muestra como "--").
- `pni` es **intermitente** (se mide cada cierto tiempo): lleva su propio `ts` con la hora de la última medición; entre mediciones se repite el último valor.
- Unidades fijas en este contrato (no se cambian sin subir la versión).
- `confianza` (0–1) es **opcional** por signo desde `1.1`: qué tan segura fue la lectura
  (la produce la fuente OCR, que es falible por diseño). Las fuentes digitales pueden
  omitirla. La web actual la ignora, así que su ausencia o presencia no rompe nada.

## 4. Mensaje de estado (JSON)

Tema `monitoreo/estado/{cama_id}`:

```json
{ "cama_id": "cama-01", "device_id": "edge-01", "estado": "online", "ts": "2026-06-09T20:15:03Z" }
```

`estado`: `"online"` | `"offline"`. Permite a la web marcar una cama como desconectada.

## 5. Correspondencia con el video

El video de cada cama se publica en el servidor (MediaMTX) usando el **mismo** `cama_id` como nombre del stream:

```
WebRTC:  http://<servidor>:8889/cama-01
RTSP in: rtsp://<servidor>:8554/cama-01   (lo publica el edge)
```

Así la web, para `cama-01`, sabe que el video está en `/cama-01` y los datos en `monitoreo/vitales/cama-01`.

## 6. Versionado
El campo `contrato` permite evolucionar sin romper. Cambios compatibles (añadir un signo o un campo opcional) mantienen `1.x`; cambios incompatibles (renombrar campos, cambiar unidades) suben a `2.0`.

| Versión | Fecha | Cambios |
|---------|-------|---------|
| `1.0` | jun 2026 | Formato inicial (Hito 2). |
| `1.1` | jul 2026 | `origen` puede valer `"ocr"`; cada signo puede llevar `confianza` (0–1) opcional. **Retrocompatible**: la web construida contra `1.0` ignora los campos nuevos. |

## 7. Futuro (fuera del Hito 2, anotado)
- **Curvas** (ECG, pletismografía, respiración) a mayor frecuencia, en un tema aparte `monitoreo/ondas/{cama_id}`.
- **Alarmas**: lista de alarmas activas por cama (ligado a la lógica de anomalías y a la "caja negra").
- **Adaptador real**: traductor HL7 v2.3.1 / Mindray PDS → este mismo JSON.
