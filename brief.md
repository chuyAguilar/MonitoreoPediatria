# brief.md — Iteración 12: Supervisión systemd del edge (OCR + video)

> Para Claude Code. Lee este brief + los 3 MVD y: `ocr/publicar.py`, `ocr/publicador.py`,
> `video/transmitir.py`, y `persistencia/vitales-ingest.service` (la plantilla systemd que ya
> existe, a espejar). Devuelve un **PLAN** (no ejecutes todavía). Lo valoramos Dr. Milton y Cowork.

## 1. Problema

Los runners del edge (`python -m ocr.publicar` y `python -m video.transmitir`) hoy se corren **a mano** en la Jetson dentro de una sesión SSH. Si se cierra el SSH, se duerme la laptop, o la Jetson reinicia, **mueren y no reviven**. La noche del 5-sep el OCR corrió en primer plano y se cayó; el parche fue un `nohup bash -c 'while true; ...'` manual — funciona pero no sobrevive un reboot, no arranca solo al encender, no da cierre limpio y no escala a multi-cama.

Agravante propio del OCR: por diseño (nunca sirve un frame viejo), ante fallo de lectura **se sale** (p. ej. cuando la Mac se duerme y la capturadora ve negro). O sea: el OCR va a salir y re-arrancar seguido durante una noche normal — el supervisor debe tolerarlo, no rendirse.

## 2. Objetivo

Supervisar ambos runners con **systemd** en la Jetson (`Restart=always`), de modo que: arranquen solos al encender, revivan tras cerrar SSH / dormir la Mac / crash / reboot, den cierre limpio en `stop`, y estén listos para **multi-cama**. Reemplaza el `nohup+while` manual. Entregable = **plantillas de unit** en el repo (a espejar de `vitales-ingest.service`) + docs; el despliegue en la Jetson lo hace Dr. Milton.

## 3. Reglas y restricciones

- **Nada de `conda activate` en el unit.** El OCR vive en el env conda `ocr-monitoreo` (Python 3.10). El `ExecStart` debe apuntar al python del env por ruta absoluta (algo como `/home/jetson/miniconda3/envs/ocr-monitoreo/bin/python -m ocr.publicar ...`). Determina/parametriza la ruta real del env en la Jetson.
- **`WorkingDirectory` = raíz del repo** en la Jetson (para que el `-m ocr.publicar` / `-m video.transmitir` importe bien). `User=jetson`.
- **Relajar el límite de arranque de systemd.** Con el `Restart=always` por defecto, systemd trae `StartLimitBurst=5` en `StartLimitIntervalSec=10s`: 5 salidas rápidas y systemd marca la unit `failed` y **deja de reintentar**. Como el OCR sale a propósito cuando la fuente está en negro, eso mataría justo lo que queremos. Hay que **desactivar/ampliar** el límite (`StartLimitIntervalSec=0`, o un burst generoso) + `RestartSec=5`. Esta es la diferencia clave contra `vitales-ingest.service` (que usa `Restart=on-failure` y no enfrenta salidas intencionales).
- **Cierre limpio en `systemctl stop`.** systemd manda **SIGTERM**. El runner de video **ya** maneja SIGTERM con cierre limpio (ver su docstring). El OCR hoy solo atrapa `KeyboardInterrupt` (SIGINT), no SIGTERM → un `stop` lo mataría sin correr `cerrar()`/offline (aunque el **Last Will** del broker publicaría el offline de rebote, ADR-022). Propón manejar SIGTERM en `ocr.publicar` para un offline **inmediato y limpio** (o justifica quedarte solo con el LWT). Esto es lo único que podría tocar **código** de módulo — márcalo explícito en el plan.
- **Multi-cama es un valor de primera clase** (CONTEXT §1): no asumir una sola cama. Propón el patrón **templated unit** (`ocr-publicar@.service`, instancia `%i` = `cama_id`) con la config por cama (`--dispositivo`, `--cama-id`, `--broker`, `--device-id`) en un `EnvironmentFile` por instancia (p. ej. `/etc/monitoreo/cama-%i.conf`). Si prefieres entregar primero una unit simple de una cama con nota de cómo escalar, dilo — pero el diseño objetivo es el templated.
- **Identidad estable de dispositivo** (ADR-018/020): las units usan el **serial** de la capturadora (`35562055`) y el **by-path** de la webcam (`usb-0:2.3`), no `/dev/videoN`.
- **No romper nada existente**: el `nohup+while` es solo un parche manual, no vive en el repo; retrocompatibilidad no aplica. No tocar el servidor (eso es de alfred) ni el front.

## 4. Alcance sugerido (a confirmar en el plan)

- Plantillas de unit en el repo, a espejar de `persistencia/vitales-ingest.service`, con cabecera de instalación (qué hacer antes de `enable --now`): p. ej. `ocr/ocr-publicar@.service` y `video/video-transmitir@.service` (nombres a tu criterio).
- Si hace falta: manejar **SIGTERM** en `ocr/publicar.py` para el offline limpio (mínimo, delante del `finally` que ya existe).
- Un `EnvironmentFile` de ejemplo por cama (`cama-09`) documentado.
- Docs: actualizar el runbook de despliegue de la Jetson (`ocr/README.md` §"desplegar en la Jetson" y `docs/ito2/REPRODUCIR_DESDE_CERO.md`) para usar systemd en vez del `nohup`; ADR corto (supervisión systemd del edge).
- Tests: si se toca `ocr.publicar` (SIGTERM), un test de que la señal dispara el cierre limpio (publica offline). Las units en sí se validan en banco.

## 5. Dudas a marcar

- **SIGTERM en el OCR** para offline inmediato, ¿sí o nos quedamos con el LWT del broker? (tu recomendación).
- **Templated `@.service` desde ya** vs. unit simple de una cama primero (recomiendo templated, pero valora el costo).
- Ruta real del env conda y del repo en la Jetson: ¿las fijamos en el unit o las parametrizamos por `EnvironmentFile`?
- ¿El video necesita systemd también, o su auto-relanzamiento (ADR-020) + un `nohup` basta? (recomiendo systemd para ambos: boot-persistencia + reinicio ante salida dura; su backoff interno cubre el mid-corrida).

## 6. Prueba de aceptación

- Units correctas y revisables (systemd no se corre en el sandbox): `ExecStart` con el python del env, `WorkingDirectory` en la raíz, `Restart=always` + `RestartSec` + límite de arranque **relajado**, identidad estable de dispositivo.
- Si se toca `ocr.publicar`: SIGTERM dispara el cierre limpio (offline), y `compileall`/suite verde.
- Banco (Dr. Milton): `enable --now` → la cama aparece; `systemctl stop` → offline; **dormir la Mac** (capturadora en negro) → el OCR sale y systemd lo **revive** solo (sin rendirse); **reboot** de la Jetson → ambos arrancan solos.

## 7. Fuera de alcance

La interfaz visual para operar el edge, el arranque headless completo / administración remota, auth/TLS, y cualquier cambio en el servidor (alfred). Aquí solo: supervisión systemd de los dos runners + el mínimo de código para el cierre limpio.
