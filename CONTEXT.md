# CONTEXT — Reglas, límites, entorno y estado

> Contexto operativo del proyecto: qué reglas de negocio manda, dónde están los límites de
> seguridad/privacidad, qué variables de entorno importan, en qué estado está el trabajo y qué
> debe respetar cualquier IA/colaborador que toque el código.
> Complementa [`ARCHITECTURE.md`](ARCHITECTURE.md) (el *qué*) y [`DECISIONS.md`](DECISIONS.md) (el *porqué*).

**Última actualización:** 2026-07-22

---

## 1. Reglas de negocio

- **Herramienta secundaria, no clínica.** El sistema **observa**; NO sustituye al monitor de
  signos vitales certificado ni al juicio del personal. Ninguna decisión clínica debe depender
  únicamente de esta plataforma. Este principio manda por encima de cualquier funcionalidad.
- **El dato puede ser erróneo.** Con OCR la lectura es *falible* por diseño. Los valores llevan
  `confianza` y se validan por rango; el sistema nunca debe presentar una lectura dudosa como
  certera.
- **Ni parcial ni incoherente.** La presión (PNI) se publica con sis/dia/media completas y en
  orden fisiológico, o no se publica. Un trío imposible es tan engañoso como uno incompleto, y
  como los rangos de los tres componentes se solapan, cada número puede ser plausible por
  separado siendo el conjunto absurdo. Vale como principio general: al validar un dato
  compuesto, comprobar también la coherencia **entre** sus partes.
- **Multi-cama desde el diseño.** Toda dato y todo video llevan `cama_id`. Nada es "la única
  cama"; el código no debe asumir una sola cama/cámara/Jetson.
- **Alarmas con criterio, no ruido.** La lógica de alertas (futura) debe disparar **solo ante
  anomalías muy fuera de lo común**. Un neonato en terapia intensiva siempre tendrá lecturas
  atípicas; saturar de alarmas genera fatiga y es contraproducente.
- **"Caja negra" (requisito de Luis Enrique).** A futuro: registro/log completo de lo que pasó,
  para auditoría. Aún no implementado.

---

## 2. Límites de seguridad y privacidad

- **Datos de pacientes = sensibles.** Los signos vitales y el video son información de salud de
  menores. No deben salir de la red privada ni subirse a servicios de terceros.
- **Todo sobre Tailscale.** La comunicación entre máquinas va cifrada por la tailnet. Nada de
  exponer puertos a internet abierto.
- **Repositorio sin datos de pacientes.** El repo Git es público (`github.com/chuyAguilar/MonitoreoPediatria`).
  **Nunca** commitear: datos reales de pacientes, video/imágenes de pacientes, IPs privadas
  sensibles fuera de las ya documentadas, credenciales, ni `.env.local` con secretos.
- **Estado actual = desarrollo, no endurecido.** Hoy:
  - Mosquitto con `allow_anonymous true` (sin auth).
  - Web servida por `http` (no `https`) dentro de la tailnet.
  - Sin autenticación de usuarios en el dashboard.
  Esto es **aceptable solo para el POC/desarrollo**. Antes de un despliegue hospitalario real
  hay que: auth en MQTT (usuario/contraseña o TLS), TLS en la web, control de acceso al
  dashboard, y revisar retención/borrado de datos.
- **Salud del menor por encima de la función.** Cualquier cambio que pudiera inducir confianza
  indebida en una lectura, ocultar una desconexión, o silenciar una anomalía real, debe evitarse.

---

## 3. Máquinas y red (tailnet)

| Rol | Nombre | Tailscale IP | Notas |
|---|---|---|---|
| **Servidor** (Gateway) | `gateway` | `100.110.157.112` | Celeron N4020, 3.6 GB RAM, Ubuntu Server. Mosquitto + MediaMTX + web. Disco USB para almacenamiento. Usuario ssh `chuy`. |
| **Edge (POC previo)** | `chuypc` | `100.72.226.69` | MacBook Pro 2014, Linux Mint. En el paradigma nuevo: **reproduce el video externo del monitor**. Usuario `chuy`. |
| **Mando / visor** | `bigdaddy` | `100.69.158.31` | PC Windows 11, i5 10th, 16 GB, RTX 3060. Navegador; build de la web; IA pesada a futuro. |
| **Edge nuevo** | `jetson-01`… | (por asignar) | Jetson Orin Nano: capturadora + OCR + cámaras. `device_id` en el contrato. |

---

## 4. Variables de entorno y puertos clave

### Web (`web/nextapp/.env.local`) — prefijo `NEXT_PUBLIC_`

| Variable | Valor actual | Qué controla |
|---|---|---|
| `NEXT_PUBLIC_SERVIDOR` | `100.110.157.112` | IP base del servidor |
| `NEXT_PUBLIC_MQTT_WS_URL` | `ws://100.110.157.112:9001` | Broker MQTT sobre WebSocket |
| `NEXT_PUBLIC_WEBRTC_BASE` | `http://100.110.157.112:8889` | Base WebRTC/WHEP de MediaMTX |

Constantes en `web/nextapp/lib/config.ts`: `TIMEOUT_DATOS_MS = 5000` (sin vitales → cama
desconectada), `WHEP_RETRY_MS = 5000` (reintento de video cuando aún no hay publisher).

### Puertos del servidor

| Puerto | Servicio | Uso |
|---|---|---|
| `1883` | Mosquitto | MQTT (edges publican) |
| `9001` | Mosquitto | MQTT sobre WebSocket (web consume) |
| `8554` | MediaMTX | RTSP in (edges publican video) |
| `8889` | MediaMTX | WebRTC/WHEP out (web consume) |
| `8080` | http.server | Web estática (systemd `dashboard`) |

Config Mosquitto: `/etc/mosquitto/conf.d/monitoreo.conf` (listener `1883 0.0.0.0` explícito +
listener `9001` websockets). MediaMTX y la web corren como servicios systemd en el servidor.

### Simulador (banco de pruebas)

`python simulador/run.py --server 100.110.157.112` (broker MQTT + destino RTSP). Flags útiles:
`--sin-video`, `--solo-consola`, `--camas N`, `--camara DEV:CAMA`. Detalle en
`docs/ito2/SIMULADOR.md`.

---

## 5. Estado actual / WIP

**Funcionando (probado end-to-end, Hitos 1–2):**
- Servidor: Mosquitto + MediaMTX + web estática desplegados (systemd).
- Transporte de vitales (MQTT) y de video (RTSP→WebRTC) validado multi-cama.
- Web Next.js: grid de camas con vitales + video, descubrimiento por topics.
- Simulador emitiendo el contrato; camino de datos validado.

**En construcción (paradigma nuevo):**
- Módulo **`ocr/`**: **iteraciones 1–6 hechas** — lectura offline de imagen fija →
  contrato `1.1` con `confianza` real por signo; perfiles con signo ausente y campo
  combinado (PNI `120/75`); perfil calibrado del monitor real de pruebas (SimCore).
- **Motor de producción: RapidOCR/ONNX Runtime** (ADR-017; sustituye a PaddleOCR de ADR-016,
  cuyo motor de inferencia segfaultea en la Jetson aarch64). Mismos modelos PP-OCR, backend
  `onnxruntime` estable en la Orin; paridad de lectura medida con Paddle (6/6, 9/9, 0 falsos)
  y ~21× más rápido en CPU (88 ms/frame); modelos empaquetados en el wheel → **offline de
  fábrica**. El motor de plantilla queda como andamiaje sin dependencias (tests + mock);
  Paddle queda como adaptador alternativo x86_64 sin declarar. La dependencia del motor real
  es **opcional** (`ocr/requirements-motor.txt`); sin ella el módulo **falla fuerte**, no lee
  en silencio.
- **Puente OCR → MQTT hecho** (iteración 4): `python -m ocr.publicar` lee frames en bucle,
  los pasa por `leer_imagen()` y publica el contrato por MQTT (vitales + estado online/offline,
  QoS 1 retained), de modo que la cama aparece en el dashboard existente end-to-end. Solo
  transporta lo que el OCR validó (publica los `null`).
- **Captura en vivo lista** (iteración 5): `FuenteCapturadora` lee la capturadora HDMI→USB
  de la Jetson por V4L2 (MJPG 1920×1080, descarta frames de arranque; ante fallo de lectura
  lanza — nunca sirve un frame viejo). `--fuente capturadora --dispositivo /dev/video0`.
  El perfil de SimCore quedó **calibrado contra el frame real de la capturadora**
  (`frame_capturadora.png`) y verificado también sobre el screenshot: un solo perfil lee
  ambos frames de referencia. Runbook de despliegue en `ocr/README.md` (env Python 3.10
  aislado, sin tocar ROS).
- Después: **corrida en vivo end-to-end en el banco** (la valida Dr. Milton: SimCore →
  capturadora → Jetson con RapidOCR → dashboard); multi-cama; reconfirmar contra el
  **uMEC12 real** cuando llegue; seguimiento de ms/frame de RapidOCR en la Orin.
- La decisión del motor se tomó con la muestra de SimCore; se **reconfirmará con el uMEC12
  real** cuando llegue de la capturadora.
- Reproducción del **video externo del monitor** en la Mac como fuente de prueba del OCR.

**Pendiente / futuro (no empezado):**
- Autenticación (MQTT + web) y TLS para despliegue real (ver §2).
- Persistencia + "caja negra" (log/almacenamiento auditable).
- Lógica de alarmas por anomalías (con criterio anti-fatiga).
- Respiración por cámara de profundidad (Femto Bolt) + IA.
- `git push` de la migración Next.js + simulador + docs ito2 si sigue pendiente.

---

## 6. Restricciones para la IA / colaboradores

- **No romper el contrato de datos.** Cambios al contrato son aditivos y versionados
  (`1.x` compatible; incompatibles → `2.0`). No renombrar campos ni cambiar unidades sin subir
  versión y actualizar `docs/ito2/CONTRATO_DATOS.md`, el simulador y la web a la vez.
- **No tocar servidor/web al cambiar la fuente del dato.** El valor de todo el diseño es que la
  fuente (simulador / OCR / HL7) sea intercambiable. Si algo obliga a modificar la web para
  soportar el OCR, revisar primero si se puede resolver dentro del contrato.
- **Cuidado al escribir archivos Python del proyecto** (lección repetida del historial): el
  editor ha corrompido archivos (líneas truncadas/vacías → `SyntaxError`/`IndentationError`).
  Tras editar, **verificar en disco** con `py_compile` y, si falla, reescribir el archivo
  completo de forma determinista (heredoc por bash), no por parches sucesivos.
- **No commitear datos de pacientes ni secretos** (ver §2).
- **Preferir cambios pequeños y verificables.** Este es un sistema con implicaciones de salud;
  ante la duda, priorizar seguridad y claridad sobre features.
- **Nombres:** `cama-NN` (dos dígitos), `jetson-NN`/`edge-NN` para `device_id`.

---

## 7. Documentación de referencia

- Arquitectura y diagramas: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Decisiones (ADRs): [`DECISIONS.md`](DECISIONS.md)
- Contrato de datos completo: [`docs/ito2/CONTRATO_DATOS.md`](docs/ito2/CONTRATO_DATOS.md)
- Runbook de despliegue desde cero: [`docs/ito2/REPRODUCIR_DESDE_CERO.md`](docs/ito2/REPRODUCIR_DESDE_CERO.md)
- Simulador: [`docs/ito2/SIMULADOR.md`](docs/ito2/SIMULADOR.md)
- Hitos: [`docs/ito1/HITO1.md`](docs/ito1/HITO1.md) · [`docs/ito2/HITO2.md`](docs/ito2/HITO2.md)
