# Prompt para Antigravity — interfaz web de monitoreo

Copia el bloque de abajo en Antigravity. Está pensado para que construya la web del Hito 2 contra el contrato de datos ya definido.

---

## PROMPT

Construye una aplicación web de tablero (dashboard) para monitoreo pediátrico en una unidad de cuidados. Muestra, en tiempo real, una **cuadrícula de camas**; cada cama tiene su **video en vivo** y sus **signos vitales**. Es una herramienta secundaria de observación (no sustituye al monitor clínico).

### Tecnología
- Sitio web estático: HTML + CSS + JavaScript (sin framework pesado; puedes usar JS puro o algo ligero). Debe poder servirse como archivos estáticos.
- Datos en tiempo real por **MQTT sobre WebSocket** usando la librería **MQTT.js** (vía CDN).
- Video en vivo por **WebRTC** desde un servidor MediaMTX.
- Interfaz en **español**.

### Configuración (al inicio del código, fácil de cambiar)
```js
const SERVIDOR = "100.110.157.112";
const MQTT_WS_URL = `ws://${SERVIDOR}:9001`;     // Mosquitto (MQTT sobre WebSocket)
const WEBRTC_BASE = `http://${SERVIDOR}:8889`;   // MediaMTX (WebRTC)
```

### Origen de datos — descubrimiento dinámico de camas
- Conéctate al broker MQTT en `MQTT_WS_URL` y **suscríbete** a:
  - `monitoreo/vitales/+`  → numéricos de cada cama (~1 vez/segundo)
  - `monitoreo/estado/+`   → estado online/offline de cada cama
- **No codifiques las camas a mano.** Descúbrelas dinámicamente: cada vez que llegue un mensaje con un `cama_id` nuevo, crea su tarjeta en la cuadrícula. Así la web "detecta" cuántas camas hay.

### Formato de los mensajes de vitales (contrato 1.0)
Cada mensaje en `monitoreo/vitales/{cama_id}` es un JSON así:
```json
{
  "contrato": "1.0",
  "cama_id": "cama-01",
  "device_id": "edge-01",
  "ts": "2026-06-09T20:15:03Z",
  "origen": "simulador",
  "signos": {
    "fc":   { "valor": 142,  "unidad": "lpm" },
    "spo2": { "valor": 97,   "unidad": "%" },
    "fp":   { "valor": 141,  "unidad": "lpm" },
    "fr":   { "valor": 48,   "unidad": "rpm" },
    "temp": { "valor": 36.9, "unidad": "C" },
    "pni":  { "sis": 66, "dia": 39, "media": 48, "unidad": "mmHg", "ts": "..." }
  }
}
```
Significado de cada signo:
- `fc` = frecuencia cardiaca (lpm)
- `spo2` = saturación de oxígeno (%)
- `fp` = frecuencia de pulso (lpm)
- `fr` = frecuencia respiratoria (rpm)
- `temp` = temperatura (°C)
- `pni` = presión no invasiva, sistólica/diastólica (media) en mmHg; es intermitente

Mensaje de estado en `monitoreo/estado/{cama_id}`:
```json
{ "cama_id": "cama-01", "device_id": "edge-01", "estado": "online", "ts": "..." }
```

### Video — descubrimiento de cámaras
- El video de cada cama está en MediaMTX con el **mismo** `cama_id` como nombre del stream.
- Para mostrarlo, implementa un cliente WebRTC **WHEP**: haz POST del SDP offer a `${WEBRTC_BASE}/${cama_id}/whep` y reproduce la respuesta en un `<video autoplay muted playsinline>`.
  - (Alternativa rápida si WHEP te complica: incrusta `<iframe src="${WEBRTC_BASE}/${cama_id}">`.)
- Si una cama **no tiene stream** (el WHEP falla o no responde), muestra un recuadro con "Sin cámara" en lugar del video. Así la web "detecta" qué camas tienen cámara y cuáles no.

### Interfaz
- Cuadrícula responsiva de **tarjetas de cama**. Cada tarjeta:
  - Encabezado con el `cama_id` y un indicador online/offline (verde/gris).
  - El **video** (o "Sin cámara").
  - Los **signos vitales** en números grandes y legibles, cada uno con su etiqueta y unidad. Estilo de monitor clínico: fondo oscuro y cada signo con un color distinto (por convención: FC en verde, SpO2 en cian, FR en amarillo, Temp en blanco, PNI en naranja/rojo).
  - Marca un valor como "--" si llega `null` o si no hay datos recientes (> 5 s sin mensaje = cama posiblemente desconectada).
- Clic en una tarjeta = verla en grande (vista de detalle).
- Encabezado general con el título "Monitoreo Pediatría" y cuántas camas activas hay.

### Importante
- Sin IA ni procesamiento de imagen en esta etapa: solo mostrar datos y video.
- Nada de datos de pacientes quemados en el código.
- Debe verse bien en una pantalla grande (estación central) y ser legible a distancia.

---

## Cómo probarlo mientras lo construyes
Ten corriendo en el servidor: Mosquitto (puerto 9001) y MediaMTX. En la Mac, lanza el simulador:
```bash
cd ~/MonitoreoPediatria/simulador
python run.py --camas 4 --camara video0:1
```
Eso publica 4 camas de datos y pone la webcam en `cama-01`. La web debería mostrar 4 tarjetas, con video en la cama-01 y "Sin cámara" en las otras tres.

## Nota técnica (opcional)
Si quieres que la web detecte las cámaras de forma explícita (en vez de intentar WHEP y fallar), se puede habilitar la API de MediaMTX (`api: yes`, puerto 9997) y consultar `http://SERVIDOR:9997/v3/paths/list`. No es necesario para la primera versión.
