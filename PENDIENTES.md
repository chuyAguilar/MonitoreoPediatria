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

**Última actualización:** 2026-09-25

---

## 🔴 Alta

- [ ] **[edge/back] Caja negra en el EDGE + store-and-forward** (Iteración 13, ADR-024)
  — **Fase 1 + F1.1 + F1.2 ENTREGADAS en el repo** (broker local 127.0.0.1 + bridge
  `cleansession true` con señal `monitoreo/edge/{device_id}/bridge` + ingesta local
  reusando `persistencia/` + flip `BROKER=localhost`; F1.1: el conf ya ARRANCA —
  validado arrancándolo; F1.2: timeout de datos en la app; F1.3: el null congela la
  alerta, ADR-025). Falta: (a) **la app 1.0.6
  en TODOS los teléfonos** (ítem [front] de abajo) — requisito ANTES del paso 1; (b)
  **despliegue F1 por Dr. Milton** (runbook §2.2 — chequeo NTP, verificación
  cuantitativa, prueba del corte con la app marcando "Sin conexión" en ≤25 s, prueba
  `kill -STOP` del OCR, teléfono bloqueado); (c) **Fase 2 en pausa** hasta desplegar
  F1: reenviador (cursor + lotes por bytes + ACK de aplicación) y agregador con dedup
  null-safe auditado + **pruning del edge** (~70–90 MB/día/cama). Mecanismo decidido:
  MQTT+ACK, no HTTPS (ADR-024). El interino del repoint a LAN `.130` se salta (plan B).
  **Nota para F2:** en cada reconexión el bridge re-entrega la última vital retenida y
  la BD del server la guarda otra vez con `retenido=0`. Es un duplicado exacto (con ts
  viejo) solo si esa vital ya había llegado al server antes del corte (OCR parado desde
  antes); si el OCR siguió publicando durante el corte, es la primera copia. Es
  at-least-once aceptado (ADR-021 §7); evaluar extender el dedup de F2 a los
  duplicados exactos del live en `vitales`. En `estado` NO, ni en el live ni en el
  backfill: el offline del will repite el mismo raw en cada disparo (ADR-022 §2), así
  que el dedup por (cama_id, ts, raw) del canal backfill de ADR-024 §5 **tampoco puede
  aplicarse tal cual a `estado`** (dos will durante un corte llegarían como uno y el
  histórico ocultaría una desconexión). Al retomar F2: limitarlo a `vitales` o
  deduplicar por multiplicidad (o por el id del edge).
- [ ] **[front] App 1.0.6: blindaje MQTT + enlace del edge + timeout de datos + null
  congela** (F1.1 y F1.2, ADR-024 §7; F1.3, ADR-025) — código en la rama
  `f1.1-enlace-edge` del repo del Front (suscripción explícita a `vitales/+`,
  `estado/+`, `edge/+/bridge`; despacho por topic con todo el callback blindado; estado
  propio "Sin conexión": punto ámbar, valores `--`, alertas congeladas; vitales con `ts`
  fuera de ±30 s = `--`, jamás pintadas ni evaluadas; "Sin datos" tras 10 s sin una
  vital en vivo, con prioridad Sin conexión > Sin datos > estado; un signo en `null`
  no se evalúa y su alerta queda congelada; versión visible en el header). Falta:
  revisión y merge de Dr. Milton, build del APK (versionCode 2) e instalación
  verificada en TODOS los teléfonos.

## 🟡 Media

- [ ] **[back/clínico] Pisos de plausibilidad del perfil vs. valores reales extremos**
  (sin código; decisión clínica de Dr. Milton, a tomar con el perfil del uMEC12 y ANTES
  de cualquier uso clínico — ADR-025). Los pisos del perfil SimCore (FC 20, SpO2 50,
  FR 3; `ocr/perfiles/simcore/simcore.json`) convierten en `null` valores reales
  extremos — FR 0 = apnea, SpO2 <50, FC <20 —, y como un `null` no se evalúa, desde un
  estado normal la app nunca alerta por ellos. Trade-off: esos mismos pisos bloquean
  lecturas con un dígito perdido (97 → "7" = falsa alarma). **Prerrequisito: el ítem
  de la caja de 3 dígitos de SpO2 (abajo)** — si se baja el piso de SpO2 sin arreglar
  antes la caja, el 100 mal leído como "10" pasaría como SpO2 10 % = falsa alarma cada
  vez que el paciente esté al 100. Evaluar en la misma decisión un aviso técnico "Sin
  lectura" tras N s de `null` persistente (sonda retirada, cámara desalineada, fuente
  equivocada): hoy, sin alerta previa, la tarjeta queda verde con `--` mientras dure.
- [ ] **[back] Caja de 3 dígitos para la SpO2 en el perfil del OCR** (ADR-015; nota del
  perfil SimCore): la caja actual es de 2 dígitos y la SpO2 100 % sale siempre `null`;
  con ADR-025, una alerta de SpO2 que se resuelve a 100 % queda roja con `--` hasta que
  se lea ≤99 (aceptado para el banco). **Es PRERREQUISITO del ítem de los pisos de
  plausibilidad (arriba):** con la caja de 2 dígitos, bajar el piso de SpO2 haría pasar
  un 100 mal leído como "10" = SpO2 10 %, falsa alarma. Revisar con capturas en vivo.

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

- [ ] **[front]** Auto-bump del `versionCode`; header centrado en móvil.
- [ ] **[edge] (opcional) Offline retenido al arrancar el OCR** — un `ExecStartPre` en
  `ocr-publicar@` que publique al broker local el offline de `%i` antes de cualquier
  fallo de arranque (tras un apagón con el OCR sin poder arrancar, el estado retenido
  del server, su BD y la web siguen viendo el `online` viejo; la app ya lo cubre con su
  timeout — ADR-024 §4). Si se hace, **reusa `carga_estado()`** (ADR-022 §1: un solo
  constructor del payload), nunca un JSON armado a mano en la unit.
- [ ] **[front] Reconexión MQTT de la app:** `ClienteMQTT` no llama
  `reconnect_delay_set`, así que tras un corte usa el backoff por defecto de paho
  (1 s → hasta 120 s; en el arnés de F1.2 una reconexión tardó ~12 s). El timeout ya
  muestra "Sin datos" mientras tanto (falla cerrado); alinearlo con el OCR,
  `reconnect_delay_set(1, 30)` (ADR-022 §4).
- [ ] **[front] Reutilización del proceso en Android** (preexistente): con el servicio
  en primer plano, reabrir la app corre `main()` en una sesión nueva y la instancia
  vieja (su paho, el reloj del header y el timer de F1.2) queda viva — flet no llama
  `will_unmount` al cerrar la sesión. Sin daño clínico (el estado es por instancia),
  pero cada reapertura suma una conexión MQTT y timers. Arreglo propuesto: en
  `page.on_close`, `loop_stop()` + `disconnect()` del cliente y cancelar los timers;
  validar en el teléfono.
- [ ] **[back]** Lógica de alarmas por anomalías en el back (hoy vive en el front).
- [ ] **[back]** Pipeline de grabación de video ("caja negra").
- [ ] **[back/hardware]** Perfil de ROIs del uMEC12 + reconfirmar lecturas cuando llegue
  el monitor real.
- [ ] **[back]** Seguimiento de ms/frame de RapidOCR en la Orin.
- [ ] **[hardware/futuro]** Monitor real uMEC12/Comen C80; respiración por profundidad +
  IA; multi-cama en vivo.

## ✅ Hecho reciente (contexto)

- [x] **[front] DECISIÓN: una lectura `null` del OCR borraba la alerta activa** de
  FC/SpO2/FR/Temp (hallazgo de la revisión de F1.2, preexistente) — **cerrada**
  (25-sep, decisión de Dr. Milton) con **F1.3 / ADR-025**: una lectura ilegible jamás
  se interpreta como normal; el `null` (o el signo ausente/malformado: `valor` que no es
  un número finito, PNI no entera) se pinta `--`, no se evalúa y su alerta queda
  congelada; `fuera_de_rango(None)` → `None`. La
  semántica quedó en ADR-025 (no en ADR-024, como proponía el ítem).

- [x] **[front] DECISIÓN del apagón de la Jetson → cama verde con `--`** (hallazgo ALTA
  de la revisión de F1.1, ADR-024 §4) — **cerrada** (25-sep, decisión #1 de Dr.
  Milton) con el **timeout de datos en la app** (F1.2): más de 10 s sin una vital en
  vivo, o ninguna desde que nació la tarjeta → "Sin datos", nunca verde. Cubre también
  el OCR colgado con proceso vivo y la desconexión silenciosa del teléfono. El
  `ExecStartPre` del edge queda como 🟢 opcional.

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
