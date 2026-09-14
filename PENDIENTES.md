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

**Última actualización:** 2026-09-14

---

## 🔴 Alta

- [ ] **[edge/back] Supervisión systemd del OCR+video en la Jetson** — Iteración 12:
  **código y units en el repo (ADR-023)**; falta el despliegue por Dr. Milton (matar el
  `nohup+while` ANTES del enable) y la validación de banco (stop → offline; Mac dormida
  → revive; reboot → ambos solos). En esa misma visita: **medir la memoria del OCR**
  (onnxruntime) bajo systemd y fijar `MemoryMax` en `ocr-publicar@.service` (hoy
  diferido a propósito — ADR-023).
- [ ] **[infra/alfred] Reserva DHCP de la IP del servidor (`192.168.110.130`) en el
  TP-Link** — sin reserva, un reinicio del router puede mover la IP LAN y romper los
  candidatos ICE anunciados (ADR-019).

## 🟡 Media

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
- [ ] **[back] Arranque headless / bootstrap de los edges.**
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

- [x] **[front]** `keepalive=15` (desconexión MQTT rápida); alertas en el teléfono
  (sonido/vibración/banner/notificación/foreground service); corrida en vivo end-to-end
  (OCR real → app).
