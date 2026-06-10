# Prompt para Antigravity — migrar la web a Next.js (React)

Copia el bloque de abajo en Antigravity. Migra la web actual (`web/index.html`, un solo archivo) a un proyecto Next.js con componentes, **conservando toda la funcionalidad y el diseño**, y preparado para auto-alojarse en el servidor (no en Vercel).

---

## PROMPT

Tengo una web de monitoreo en un solo archivo `web/index.html` que ya funciona: muestra una cuadrícula de camas con signos vitales en tiempo real (MQTT sobre WebSocket) y video en vivo (WebRTC WHEP). Quiero **migrarla a un proyecto Next.js (App Router)** manteniendo exactamente la misma funcionalidad y el mismo diseño (tema oscuro estilo monitor clínico). Lee `web/index.html` como referencia y porta su lógica.

### Requisitos del proyecto
- **Next.js con App Router** y TypeScript.
- **Export estático**: en `next.config`, `output: 'export'` (se va a auto-alojar como archivos estáticos en un servidor propio, sin Vercel ni backend).
- Toda la lógica que usa APIs de navegador (WebSocket/MQTT, `RTCPeerConnection`) debe ir en componentes con `'use client'` y ejecutarse dentro de `useEffect` (no en render ni en servidor).
- Librería MQTT: paquete `mqtt` (mqtt.js) de npm.

### Configuración (un solo lugar, vía variables de entorno)
Usa variables `NEXT_PUBLIC_` con estos valores por defecto:
```
NEXT_PUBLIC_SERVIDOR=100.110.157.112
NEXT_PUBLIC_MQTT_WS_URL=ws://100.110.157.112:9001
NEXT_PUBLIC_WEBRTC_BASE=http://100.110.157.112:8889
```
Léelas en un módulo `lib/config.ts`.

### Estructura sugerida
- `app/page.tsx` — página del dashboard (client component): cuadrícula de camas, descubiertas dinámicamente.
- `components/Header.tsx` — título "Monitoreo Pediatría", contador de camas activas, indicador de estado MQTT.
- `components/BedCard.tsx` — tarjeta de una cama: encabezado con `cama_id` e indicador online/offline, video y signos vitales.
- `components/VitalSign.tsx` — un signo con etiqueta, valor grande y unidad.
- `components/VideoWHEP.tsx` — reproductor WebRTC WHEP (ver lógica abajo).
- `components/DetailModal.tsx` — vista ampliada al hacer clic en una tarjeta.
- `hooks/useMqtt.ts` — hook que conecta al broker, se suscribe a `monitoreo/vitales/+` y `monitoreo/estado/+`, y mantiene un mapa de camas en estado de React (cada `cama_id` nuevo crea su tarjeta).
- `lib/whep.ts` — función para conectar WebRTC WHEP con reintento.

### Lógica a conservar (ya está en index.html)
- **Descubrimiento dinámico de camas**: las tarjetas se crean según los `cama_id` que lleguen por MQTT. No codificar camas.
- **Formato del contrato 1.0** (ver `docs/ito2/CONTRATO_DATOS.md`): campos `signos.fc/spo2/fp/fr/temp/pni` con `valor`/`unidad`; `pni` con `sis/dia/media`.
- **Colores por signo**: FC verde, SpO2 cian, FR amarillo, Temp blanco, FP verde claro, PNI naranja.
- **Timeout 5 s**: si una cama no envía mensaje en 5 s, marcarla desconectada (indicador gris, valores "--").
- **Video WHEP con reintento** (importante): conectar haciendo POST del SDP offer a `${WEBRTC_BASE}/${cama_id}/whep`. Si devuelve 404 (aún no hay stream), **reintentar cada 5 s** hasta conectar. Si `pc.connectionState` pasa a `failed`/`disconnected`, reconectar. Mostrar "Sin cámara" mientras no haya video. Limpiar la conexión (`pc.close()`) en el cleanup del `useEffect`.

### Diseño
Mantén el mismo aspecto del index.html actual: fondo oscuro, números grandes monoespaciados, cuadrícula responsiva, modal de detalle. Puedes usar CSS Modules o Tailwind, lo que te resulte más limpio.

### Build
- `npm run build` debe generar la versión estática (carpeta `out/`).
- No uses API routes ni funciones de servidor (es export estático).

---

## Después de migrar (lo hace Claude, no Antigravity)
El despliegue es auto-alojado: se construye la versión estática y se sirve desde el servidor (Gateway) en la tailnet. Claude se encargará de servir la carpeta `out/` en el servidor y dejarlo corriendo.
