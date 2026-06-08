# Monitoreo Pediatría

Plataforma de monitoreo para pediatría/neonatología: captura de signos vitales de monitores de cama, video en vivo del infante, detección de respiración con cámara de profundidad (Orbbec Femto Bolt + IA), almacenamiento tipo "caja negra" y visualización web en tiempo real.

> **Importante:** este sistema es una herramienta secundaria de observación. NO sustituye al monitor de signos vitales ni al juicio clínico.

## Arquitectura general

```
[Monitor de cama] --HDMI/serial/red--> [Edge: laptop/Raspberry/Jetson] --red--> [Servidor]
[Femto Bolt] -----USB 3.0-----------> [Edge]                                      |
                                                                   almacenamiento (caja negra)
                                                                   retransmisión (WebRTC)
                                                                   app web (dashboard + alertas)
```

## Fases

| Fase | Descripción | Estado |
|------|-------------|--------|
| 0 | Investigar monitores (marca/modelo/salidas de datos) | Esperando información |
| 1 | Captura de signos vitales del monitor → servidor → dashboard | Bloqueada por fase 0 |
| 2 | Video en vivo del infante (Femto Bolt RGB → WebRTC) | **En curso** |
| 3 | Detección de respiración (Femto Bolt profundidad + procesamiento de señal/IA) | **En curso** |

## Estructura del repositorio

```
capture/      Captura de cámara Femto Bolt (RGB + profundidad)
streaming/    Transmisión de video al servidor (ffmpeg/GStreamer → MediaMTX)
vision/       Procesamiento de profundidad: señal respiratoria, detección de apnea
server/       Configuración del servidor (MediaMTX, base de datos, docker)
web/          Dashboard web
docs/         Documentación y guías de instalación
```

## Inicio rápido

1. Sigue la guía de instalación: [`docs/INSTALACION_LAPTOP.md`](docs/INSTALACION_LAPTOP.md)
2. Conecta la Femto Bolt a un puerto USB 3.0
3. Prueba la captura:

```bash
source ~/orbbec_env/bin/activate
python capture/femtobolt_test.py
```

## Hardware del proyecto

- Cámara Orbbec Femto Bolt (RGB 4K + profundidad ToF) — requiere USB 3.0
- Laptop MacBook Pro 2014 con Ubuntu — servidor + estación de captura (PoC)
- Capturadora HDMI — para la fase 1 (video del monitor / OCR de respaldo)
