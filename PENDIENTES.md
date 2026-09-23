# PENDIENTES — Backlog vivo del proyecto

> Cuarto documento del MVD (junto a [`ARCHITECTURE.md`](ARCHITECTURE.md),
> [`DECISIONS.md`](DECISIONS.md) y [`CONTEXT.md`](CONTEXT.md)): el backlog priorizado de
> lo que falta. Se actualiza al abrir/cerrar trabajo; el detalle del *porqué* vive en los
> ADRs y el *estado* narrativo en CONTEXT §5 — aquí solo la lista accionable.
>
> **Prioridades**: 🔴 Alta · 🟡 Media · 🟢 Baja–Futuro.
> **Dueños**: `[front]` app Flet (vive en **repo aparte**; aquí solo se lista) ·
> `[back]` este repo · `[infra/alfred]` el agente del servidor · `[edge]` la Jetson ·
> `[hardware]` equipos físicos.

**Última actualización:** 2026-09-22

---

## 🔴 Alta

- [ ] **[edge/back] Caja negra en el EDGE + store-and-forward** (Iteración 13, ADR-024)
  — **Fase 1 + F1.1 ENTREGADAS en el repo** (broker local 127.0.0.1 + bridge
  `cleansession true` con señal `monitoreo/edge/{device_id}/bridge` + ingesta local
  reusando `persistencia/` + flip `BROKER=localhost`; F1.1: el conf ya ARRANCA —
  validado arrancándolo). Falta: (a) **la app 1.0.6 en TODOS los teléfonos** (ítem
  [front] de abajo) — requisito ANTES del paso 1; (b) **despliegue F1 por Dr. Milton**
  (runbook §2.2 — chequeo NTP, verificación cuantitativa, prueba del corte con la app
  marcando "Sin conexión" en ≤25 s); (c) **Fase 2 en pausa** hasta desplegar F1:
  reenviador (cursor + lotes por bytes + ACK de aplicación) y agregador con dedup
  null-safe auditado + **pruning del edge** (~70–90 MB/día/cama). Mecanismo decidido:
  MQTT+ACK, no HTTPS (ADR-024). El interino del repoint a LAN `.130` se salta (plan B).
- [ ] **[front] App 1.0.6: blindaje MQTT + consumo del enlace del edge** (F1.1,
  ADR-024 §7) — código en la rama `f1.1-enlace-edge` del repo del Front (suscripción
  explícita a `vitales/+`, `estado/+`, `edge/+/bridge`; despacho por topic con todo el
  callback blindado; estado propio "Sin conexión": punto ámbar, valores `--`, alertas
  congeladas; vitales con `ts` fuera de ±30 s = `--`, jamás pintadas ni evaluadas;
  versión visible en el header). Falta: revisión y merge de Dr. Milton, build del APK
  (versionCode 2) e instalación verificada en TODOS los teléfonos.
- [ ] **[edge/front] DECISIÓN: apagón de la Jetson con el OCR sin poder arrancar →
  cama VERDE con `--`** (hallazgo ALTA de la revisión de F1.1, ADR-024 §4). Tras el
  flip el will del OCR muere con el broker local; al volver la energía el broker
  restaura el `online` viejo y el bridge lo re-publica. Si el OCR no arranca
  (capturadora ausente: sale antes de conectar MQTT), nadie publica offline. Las
  vitales viejas ya NO se pintan (frescura), pero el punto queda verde. Opciones: (1)
  `[edge]` `ExecStartPre` en `ocr-publicar@` que publique al broker local el offline
  retenido del contrato para `%i` (arregla app, web y BD del server en la fuente;
  requiere `mosquitto-clients`, ya en el runbook); (2) `[front]` timeout de datos: sin
  vital fresca en N s, el punto deja el verde (sube el ítem 🟢 de abajo). No bloquea
  el despliegue de F1 si se acepta como limitación conocida.

## 🟡 Media

- [ ] **[edge] Medir la memoria del OCR bajo systemd y fijar `MemoryMax`** en
  `ocr-publicar@.service` (era sub-tarea del supervisor systemd; diferida a propósito
  hasta medir en banco — ADR-023).
- [ ] **[hardware/edge] Pila RTC de la Jetson** (riesgo detectado por Cowork en F1.1):
  un reinicio SIN internet arranca con el reloj mal (sin RTC con pila o con la pila
  agotada, no hay hora hasta que NTP sincroniza) y el `recibido_en` de la caja negra
  local — la línea de tiempo del histórico y del backfill — queda inservible. El
  chequeo NTP del runbook solo cubre la instalación. Verificar/instalar la pila RTC;
  mitigación de software opcional para F2/F3: evento en `eventos_ingesta` si el reloj
  retrocede o si la ingesta arranca sin NTP sincronizado.
- [ ] **[back] Frescura de vitales en la web** (ADR-024 §2): al volver el enlace, el
  bridge re-entrega la última vital retenida como mensaje en vivo; `handleVitales`
  (`web/nextapp/hooks/useMqtt.ts`) fuerza `online: true` y la pinta hasta que salta el
  watchdog de 5 s. Mismo criterio que la app: descartar la vital cuyo `ts` esté fuera
  de ±30 s. (La web NO lee `monitoreo/edge/+/bridge`: su watchdog de datos cubre la
  caída.)
- [ ] **[edge] Anotar la versión de mosquitto de la Jetson** (runbook §2.2 paso 1;
  Ubuntu 22.04 trae 2.0.11, la validación de F1.1 fue con 2.0.18 — la prueba del
  corte en banco es la validación en la versión objetivo).
- [ ] **[infra/alfred] Watchdog de la ingesta** — timer systemd en el servidor (sin usar el
  modelo) que detecte "más de X min sin filas nuevas" y lo registre, para que el próximo hueco
  no pase días invisible (como el de 4.5 días). Alfred lo ofreció; falta el OK y montarlo.
  Desde ADR-024 debe **distinguir "corte de enlace" de "edge caído"** mirando
  `monitoreo/edge/{device_id}/bridge` (retained 1/0) — y tras la F2, "sin filas nuevas"
  durante un corte es esperado (el backfill las traerá).
- [ ] **[infra→Dr. Milton] Cerrar el riesgo de conflicto de la `.130` en el router** —
  la IP estática del server ya la puso alfred (ver ✅), pero NO se pudo verificar si `.130`
  cae dentro del pool DHCP del TP-Link. Si cae, el router podría dársela a otro equipo →
  conflicto. Cuando recuperes acceso al router (falta contraseña de admin desde junio):
  reservar `00-E0-4C-88-00-5D → .130` **o** excluir `.130` del pool. No urge (belt-and-suspenders).
- [ ] **[back/docs] Actualizar ADR-019 + runbook con la IP `.130`** (hoy documentan
  `192.168.110.4` en `webrtcAdditionalHosts`).
- [ ] **[front] Probar la notificación en segundo plano** (app minimizada).
- [ ] **[front] Valores clínicos reales del perfil `neonato`**; agregar `lactante` /
  `adulto`.
- [ ] **[back] Validación en banco del runner de video** (restart de MediaMTX en vivo;
  estancamiento por corte TCP con la regla iptables — ADR-020).
- [ ] **[back] Retención/pruning de las BD** — ahora son DOS (ADR-024): la del **edge**
  entra en la Fase 2 (borrar `id <= cursor` confirmado, con margen — ya diseñado); la
  del **server** sigue con la política de la "caja negra" (ADR-021).
- [ ] **[infra/alfred] Backup de la BD SQLite del server + vigilar el disco USB** (la
  eMMC/el disco son hoy la única copia — ADR-021; tras la F2 de ADR-024, la BD del edge
  actúa además de réplica temporal de lo aún no reenviado).
- [ ] **[edge] Vigilancia de disco de la Jetson** (ADR-024): ~70–90 MB/día/cama sin
  pruning hasta F2; mientras, `df -h` en cada visita al banco.
- [ ] **[infra/alfred] Seguridad de servidor (pre-hospital)**: auth MQTT, TLS web,
  control de acceso al dashboard, auth de MediaMTX (CONTEXT §2). **+ [back]** el lado
  cliente de esa auth/TLS (edges, ingesta, web).
- [ ] **[back] Administración/monitoreo remoto de los edges + alta de camas** (el
  auto-arranque al bootear ya lo cubre el systemd de la Iteración 12; falta lo remoto y
  el provisioning — se junta con la interfaz visual).
- [ ] **[back] Interfaz visual para operar el backend** — feature grande: diseñar
  primero, no improvisar.
- [ ] **[infra/alfred] Salud continua de los servicios del servidor.**

## 🟢 Baja–Futuro

- [ ] **[front]** Timeout de datos en la app (sube a 🔴 si se elige como cierre de la
  DECISIÓN del apagón de arriba); auto-bump del `versionCode`; header centrado en móvil.
- [ ] **[back]** Lógica de alarmas por anomalías en el back (hoy vive en el front).
- [ ] **[back]** Pipeline de grabación de video ("caja negra").
- [ ] **[back/hardware]** Perfil de ROIs del uMEC12 + reconfirmar lecturas cuando llegue
  el monitor real.
- [ ] **[back]** Seguimiento de ms/frame de RapidOCR en la Orin.
- [ ] **[hardware/futuro]** Monitor real uMEC12/Comen C80; respiración por profundidad +
  IA; multi-cama en vivo.

## ✅ Hecho reciente (contexto)

- [x] **[infra/alfred] IP estática del servidor `192.168.110.130`** (22-sep) — fijada
  server-side vía netplan (`/etc/netplan/99-ip-estatica.yaml`, con respaldo), NO depende del
  router, sobrevive reinicios. Cierra el ciclo "reinicio → IP nueva → WebRTC roto". Contexto:
  se descubrió un hueco de ~4.5 días en la BD (17-20 sep) por caída de internet + la Jetson
  publicando a la IP de Tailscale — de ahí la Iteración 13 / ADR-024 (🔴 arriba); el
  interino de repuntar a la LAN se saltó y queda de plan B.
- [x] **[edge/back] Supervisión systemd del edge (Iteración 12, ADR-023)** — desplegada y
  **validada en banco** (15-sep): `stop`→offline, `SIGKILL`→revive en ~5 s, reboot→ambos
  `active` solos. Reemplaza el `nohup+while` manual. Nota de campo: la Jetson usa
  `miniforge3` (no miniconda3); el video corre con el python del sistema. Pendiente
  derivado: `MemoryMax` (arriba, 🟡).
- [x] **[front]** `keepalive=15` (desconexión MQTT rápida); alertas en el teléfono
  (sonido/vibración/banner/notificación/foreground service); corrida en vivo end-to-end
  (OCR real → app).
