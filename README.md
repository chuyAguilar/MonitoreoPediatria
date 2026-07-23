# Monitoreo Pediatría

Plataforma de monitoreo para pediatría/neonatología: muestra en tiempo real, en un tablero web, varias camas a la vez con sus **signos vitales** (leídos del monitor de cama) y su **video en vivo**, servida desde un servidor propio. A futuro: detección de respiración con cámara de profundidad (Orbbec Femto Bolt + IA) y almacenamiento tipo "caja negra".

> **Importante:** este sistema es una herramienta secundaria de observación. NO sustituye al monitor de signos vitales ni al juicio clínico.

## Documentación mínima viable (MVD)

Antes de tocar código, empieza por estos tres documentos:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — topología, componentes, flujo de datos y diagramas.
- [`DECISIONS.md`](DECISIONS.md) — registro de decisiones de arquitectura (ADRs) y sus porqués.
- [`CONTEXT.md`](CONTEXT.md) — reglas de negocio, límites de seguridad, variables de entorno, estado/WIP y restricciones para colaboradores.

## Cómo se obtiene el dato (paradigma actual)

El signo vital se **lee de la pantalla del monitor con OCR**, no de un protocolo digital:

```
[Monitor] --HDMI--> [Capturadora + OCR en Jetson Orin Nano] --datos MQTT-->
[Cámara por cama] ---------------------------------------- --video RTSP-->
                                                                  |
                                        [Servidor: Mosquitto + MediaMTX + web]
                                                                  |
                                        --MQTT-WS + WebRTC + web-->
                                                                  v
                                                   [Navegador: grid de camas]
```

- **1 cama = 1 monitor + 1 cámara.** Cada cama lleva su `cama_id`, que es a la vez el topic MQTT y el nombre del stream de video.
- **Jetson Orin Nano** = edge (`device_id`): captura la pantalla del monitor por una capturadora HDMI, corre el OCR y encodea las cámaras. Una Jetson cubre **N camas**; puede haber **varias Jetsons**.
- La fuente del dato es **intercambiable por contrato**: el OCR emite el mismo JSON que emitía el simulador (ver contrato de datos), así el servidor y la web no cambian. Todo cifrado sobre Tailscale.

> El paradigma anterior (dato digital por simulador o HL7/PDS del monitor Mindray) está documentado como histórico en [`DECISIONS.md`](DECISIONS.md) (ADR-002, ADR-012). El **simulador se conserva** como banco de pruebas de la web.

## Hitos

| Hito | Descripción | Estado |
|------|-------------|--------|
| 1 | Video en vivo de extremo a extremo (cámara → servidor → navegador) | ✅ Completo |
| 2 | Datos del monitor (simulados) + video + web multi-cama | ✅ Completo |
| 3 (actual) | Captura por video + **OCR en Jetson** → mismo contrato | 🔨 En curso |
| 4 (futuro) | Persistencia/"caja negra", alarmas por anomalías, respiración con IA | Pendiente |

## Estructura del repositorio

```
capture/      Captura de cámara Femto Bolt (RGB + profundidad) — Hito 1 / futuro
simulador/    Simulador (legacy): datos MQTT + video webcam. Banco de pruebas de la web.
ocr/          Lectura de signos por OCR: imagen fija → contrato 1.1 (ver ocr/README.md).
              Pendiente: capturadora en vivo y publicación MQTT.
web/nextapp/  Dashboard web (Next.js, export estático)
docs/ito1/    Documentación e imágenes del Hito 1
docs/ito2/    Documentación, contrato de datos, runbook y diagramas del Hito 2
ARCHITECTURE.md · DECISIONS.md · CONTEXT.md   Documentación mínima viable (MVD)
```

## Inicio rápido

Para montar el sistema completo desde cero (qué comando en qué equipo), ver el runbook:
[`docs/ito2/REPRODUCIR_DESDE_CERO.md`](docs/ito2/REPRODUCIR_DESDE_CERO.md)

Documentos clave:
- Contrato de datos: [`docs/ito2/CONTRATO_DATOS.md`](docs/ito2/CONTRATO_DATOS.md)
- Simulador (banco de pruebas): [`docs/ito2/SIMULADOR.md`](docs/ito2/SIMULADOR.md)
- Resumen Hito 2: [`docs/ito2/HITO2.md`](docs/ito2/HITO2.md)

## Equipos (red Tailscale)

- **Servidor** (Gateway, `100.110.157.112`): Mosquitto (datos), MediaMTX (video), web estática.
- **Jetson** (edge): capturadora + OCR + cámaras; publica datos del monitor y el video por cama.
- **Mac** (`chuypc`): en el banco de pruebas, reproduce un video externo de un monitor real.
- **Mando** (PC Windows con GPU): navegador para visualizar; a futuro, procesamiento de IA.
