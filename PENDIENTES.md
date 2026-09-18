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

**Última actualización:** 2026-09-15

---

## 🔴 Alta

_(Sin pendientes de prioridad alta en este momento — 15-sep-2026.)_

## 🟡 Media

- [ ] **[edge] Medir la memoria del OCR bajo systemd y fijar `MemoryMax`** en
  `ocr-publicar@.service` (era sub-tarea del supervisor systemd; diferida a propósito
  hasta medir en banco — ADR-023).
- [ ] **[infra→Dr. Milton] Reserva DHCP de la IP del servidor (`192.168.110.130`) en el
  TP-Link** — bajada de 🔴 a 🟡: **solo afecta el acceso por WiFi local**; por **Tailscale**
  (`100.110.157.112`, IP fija) el video funciona pase lo que pase con la IP de LAN, y un
  candidato ICE muerto no rompe a los clientes de Tailscale. La reserva evita que la entrada
  LAN de `webrtcAdditionalHosts` quede obsoleta en cada reinicio (hoy ya saltó a `.131`).
  Alfred da la MAC (`00-E0-4C-88-00-5D`, iface Ethernet); la reserva la mete Dr. Milton en el
  router cuando tenga acceso (falta la contraseña de admin, pendiente desde junio, ADR-019).
- [ ] **[back/docs] Actualizar ADR-019 + runbook con la IP `.130`** (hoy documentan
  `192.168.110.4` en `webrtcAdditionalHosts`).
- [ ] **[front] Probar la notificación en segundo plano** (app minimizada).
- [ ] **[front] Valores clínicos reales del perfil `neonato`**; agregar `lactante` /
  `adulto`.
- [ ] **[back] Validación en banco del runner de video** (restart de MediaMTX en vivo;
  estancamiento por corte TCP con la regla iptables — ADR-020).
- [ ] **[back] Retención/pruning de la BD** (código; la política la fija la "caja
  negra", ADR-021).
- [ ] **[infra/alfred] Backup de la BD SQLite + vigilar el disco USB** (la eMMC/el disco
  son hoy la única copia — ADR-021).
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

- [x] **[edge/back] Supervisión systemd del edge (Iteración 12, ADR-023)** — desplegada y
  **validada en banco** (15-sep): `stop`→offline, `SIGKILL`→revive en ~5 s, reboot→ambos
  `active` solos. Reemplaza el `nohup+while` manual. Nota de campo: la Jetson usa
  `miniforge3` (no miniconda3); el video corre con el python del sistema. Pendiente
  derivado: `MemoryMax` (arriba, 🟡).
- [x] **[front]** `keepalive=15` (desconexión MQTT rápida); alertas en el teléfono
  (sonido/vibración/banner/notificación/foreground service); corrida en vivo end-to-end
  (OCR real → app).
