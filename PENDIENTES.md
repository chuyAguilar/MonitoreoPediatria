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
  — **Fase 1 ENTREGADA en el repo** (broker local 127.0.0.1 + bridge `cleansession true`
  con señal `monitoreo/edge/{device_id}/bridge` + ingesta local reusando `persistencia/`
  + flip `BROKER=localhost`): con desplegarla, los datos quedan protegidos YA. Falta:
  (a) **despliegue F1 por Dr. Milton** (runbook §2.2 — incluye chequeo NTP y prueba del
  corte); (b) **Fase 2 en construcción**: reenviador (cursor + lotes por bytes + ACK de
  aplicación) y agregador con dedup null-safe auditado + **pruning del edge** (~70–90
  MB/día/cama; sin él la Jetson se llena). Mecanismo decidido: MQTT+ACK, no HTTPS
  (ADR-024). El interino del repoint a LAN `.130` se salta — F1 lo sustituye (plan B).

## 🟡 Media

- [ ] **[edge] Medir la memoria del OCR bajo systemd y fijar `MemoryMax`** en
  `ocr-publicar@.service` (era sub-tarea del supervisor systemd; diferida a propósito
  hasta medir en banco — ADR-023).
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

- [ ] **[front]** Timeout de datos en la app; auto-bump del `versionCode`; header
  centrado en móvil.
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
