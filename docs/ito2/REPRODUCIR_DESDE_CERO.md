# Reproducir el sistema desde cero (runbook)

Guía completa para montar el sistema del Hito 2 desde una instalación limpia, como si fuera a desplegarse junto a un monitor real. Indica **qué comando se corre en qué equipo**.

> En esta etapa el monitor se **simula**. Cuando llegue el monitor real (Mindray uMEC10), se reemplaza el simulador por un adaptador que publica el mismo contrato de datos; todo lo demás queda igual.

---

## Inventario de equipos

| Rol | Equipo | SO | Tailscale | Qué corre |
|-----|--------|----|-----------|-----------| 
| **Servidor** | Gateway (Celeron) | Ubuntu Server | `100.110.157.112` | Mosquitto (datos), MediaMTX (video), web estática, ingesta a SQLite |
| **Edge real** | Jetson Orin Nano (`jetson-01`) | JetPack 6 / Ubuntu 22.04 | `100.80.150.79` | OCR del monitor + video de la cama, como servicios systemd (ADR-023) |
| **Edge (simulación)** | laptop / Raspberry por sala | Linux (Mint/Ubuntu) | `100.72.226.69` | Simulador: publica datos + transmite webcam |
| **Mando** | PC de visualización | Windows / cualquiera | `100.69.158.31` | Navegador para ver el dashboard |

Las cuatro se unen por **Tailscale** (misma cuenta). Las IPs `100.x` son fijas de Tailscale.
Conexión al edge real: `ssh jetson@100.80.150.79` (verifica con `tailscale status`).

Puertos usados en el servidor: `1883` MQTT, `9001` MQTT-WebSocket, `8554` RTSP (entra el video), `8889` WebRTC (sale el video), `8080` web.

---

## Parte 0 — Red (en las 4 máquinas)

Instala Tailscale en cada equipo e inicia sesión con la **misma cuenta**:
- Linux: `curl -fsSL https://tailscale.com/install.sh | sh` y luego `sudo tailscale up`
- Windows: instalador de tailscale.com/download/windows

Verifica que se vean entre sí: `tailscale status` debe listar las cuatro.

---

## Parte 1 — Servidor (Gateway)

Conéctate: `ssh chuy@100.110.157.112`

### 1.1 Mosquitto (broker de datos MQTT)
```bash
sudo apt update && sudo apt install -y mosquitto mosquitto-clients
sudo tee /etc/mosquitto/conf.d/monitoreo.conf >/dev/null <<'EOF'
listener 1883 0.0.0.0
protocol mqtt

listener 9001 0.0.0.0
protocol websockets

allow_anonymous true
EOF
sudo systemctl restart mosquitto
sudo systemctl enable mosquitto
```
> `allow_anonymous true` es solo para desarrollo. En producción se añade usuario/contraseña.

### 1.2 MediaMTX (retransmisión de video) — como servicio
```bash
cd ~ && mkdir -p mediamtx && cd mediamtx
wget https://github.com/bluenviron/mediamtx/releases/download/v1.17.0/mediamtx_v1.17.0_linux_amd64.tar.gz
tar -xzf mediamtx_v1.17.0_linux_amd64.tar.gz

sudo tee /etc/systemd/system/mediamtx.service >/dev/null <<'EOF'
[Unit]
Description=MediaMTX (servidor de video)
After=network.target

[Service]
ExecStart=/home/chuy/mediamtx/mediamtx /home/chuy/mediamtx/mediamtx.yml
WorkingDirectory=/home/chuy/mediamtx
Restart=always
User=chuy

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now mediamtx
```

**Configuración WebRTC obligatoria** (lección del 12-ago-2026, ADR-019): MediaMTX debe
**anunciar sus IPs reales** como candidatos ICE. Si solo anuncia `127.0.0.1` (pasa cuando la
enumeración de interfaces falla o está restringida), todo cliente WebRTC desde otra máquina
se queda en `connecting → failed` ("Reconectando…" en el dashboard) aunque la señalización
funcione. En `/home/chuy/mediamtx/mediamtx.yml`:

```yaml
# IPs con las que los navegadores pueden alcanzar a ESTE servidor
# (Tailscale y LAN local). Sin esto, el video WebRTC no conecta cross-máquina.
webrtcAdditionalHosts: [100.110.157.112, 192.168.110.4]
```

y `sudo systemctl restart mediamtx`. Verificación rápida desde cualquier máquina de la
tailnet: la página `/diag.html?stream=<cama>` del dashboard muestra en consola los estados; si
el servidor sigue anunciando solo loopback, el dashboard lo advierte explícitamente en la
consola con el arreglo.

### 1.3 Servidor web estático (sirve el dashboard) — como servicio
Primero se necesita el build del dashboard en `~/dashboard` (ver Parte 4 para generarlo y copiarlo). Luego:
```bash
sudo tee /etc/systemd/system/dashboard.service >/dev/null <<'EOF'
[Unit]
Description=Dashboard Monitoreo Pediatria (web estatica)
After=network.target

[Service]
ExecStart=/usr/bin/python3 -m http.server 8080 --directory /home/chuy/dashboard
Restart=always
User=chuy

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard
```

### 1.4 Ingesta de vitales a SQLite — como servicio (ADR-021)

Persiste TODO mensaje de vitales y estado en una BD SQLite del servidor (histórico /
primer paso de la "caja negra"). Lo despliega **alfred**; Chuy aprueba.

```bash
# 0) Dependencias del servidor (la Parte 1 solo instala mosquitto)
sudo apt install -y git python3-venv sqlite3

# 1) Código: clon del repo (o pull) en el directorio de apps
git clone https://github.com/chuyAguilar/MonitoreoPediatria.git ~/apps/monitoreo-pediatrico
cd ~/apps/monitoreo-pediatrico
python3 -m venv venv && venv/bin/pip install paho-mqtt

# 2) La BD vive FUERA del clon (datos de pacientes: un `git clean -fdx`
#    borraría hasta lo ignorado). Crear el directorio y verificar el esquema:
mkdir -p ~/datos/monitoreo
venv/bin/python -m persistencia.ingerir --bd ~/datos/monitoreo/vitales.db --solo-esquema

# 3) Defensa del broker (única real contra un retained gigante) y cola de la
#    sesión persistente de la ingesta, en /etc/mosquitto/conf.d/monitoreo.conf:
#      message_size_limit 65536      # (en Mosquitto 2.x: max_packet_size)
#      max_queued_messages 5000     # ~8 min de ingesta caída a ~10 msg/s:
#                                   # una caída más larga pierde mensajes EN
#                                   # el broker, sin rastro en eventos_ingesta
sudo systemctl restart mosquitto

# 4) Instalar el servicio (plantilla en persistencia/vitales-ingest.service):
sudo cp persistencia/vitales-ingest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vitales-ingest

# 5) Verificar: filas creciendo mientras el simulador/OCR publica
sqlite3 ~/datos/monitoreo/vitales.db "SELECT count(*), max(ts) FROM vitales;"
# y la reconexión: sudo systemctl restart mosquitto -> count(*) sigue creciendo
```

**Reglas de operación**: UNA sola instancia (el client_id MQTT es fijo con sesión
persistente: una corrida manual con el servicio activo produce expulsión mutua en bucle —
si la ingesta reconecta sin parar, ese es el síntoma). Los huecos del propio servicio
quedan registrados en la tabla `eventos_ingesta`. Guía de lectura del histórico:
tendencias y conteos con `WHERE retenido=0 AND malformado=0` (ADR-021).

Con esto, los cuatro servicios del servidor arrancan solos al encender la máquina.

---

## Parte 2 — Edge (la máquina con la(s) webcam(s))

Conéctate: `ssh chuy@100.72.226.69`

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git ffmpeg v4l-utils
python3 -m venv ~/orbbec_env
source ~/orbbec_env/bin/activate
pip install paho-mqtt opencv-python numpy

git clone https://github.com/chuyAguilar/MonitoreoPediatria.git ~/MonitoreoPediatria
```
> Solo se necesitan `paho-mqtt`, `opencv-python` y `numpy` para el simulador con webcam. (La cámara Femto Bolt y su SDK son para el monitoreo de respiración, fase futura.)

Conecta la(s) webcam(s) por USB y lanza el simulador:
```bash
cd ~/MonitoreoPediatria/simulador
source ~/orbbec_env/bin/activate
python run.py --camas 4 --camara video0:1 --fps 15 --ancho 320 --alto 240
```
- `--camas 4`: simula 4 camas.
- `--camara video0:1`: la webcam `/dev/video0` va a la `cama-01`.
- `--fps 15 --ancho 320 --alto 240`: baja la carga para webcams genéricas (sube si tu cámara aguanta más).
- Sin argumentos (`python run.py`) entra en modo interactivo y pregunta todo.

### 2.1 Video por cama con el runner supervisado (edge real / Jetson) — ADR-020

En el edge real el video de una cama NO se transmite con un `ffmpeg` a mano (moría con
`Broken pipe` al reiniciar MediaMTX y apuntaba a un `/dev/videoN` que baila): se usa el
runner, que elige la cámara por **identidad estable**, se relanza solo con backoff y
detecta transmisiones **estancadas** (ffmpeg vivo pero congelado). Sin dependencias pip;
solo necesita `ffmpeg` instalado y correrse **desde la raíz del repo**:

```bash
cd ~/MonitoreoPediatria

# 1) Descubrir la identidad de la cámara (nombre, serial, by-id, by-path):
python -m video.transmitir --listar-dispositivos

# 2) Transmitir la cama (ejemplo real del banco: la webcam de cama-09 va por
#    su PUERTO físico, fragmento del by-path — el de la tabla de abajo):
python -m video.transmitir --cama-id cama-09 --dispositivo usb-0:2.3

# Perfil bajo para redes flojas:
python -m video.transmitir --cama-id cama-09 --dispositivo usb-0:2.3 \
  --resolucion 640x480 --bitrate 800k

# Depurar formatos de una cámara sin que el relanzador pelee contigo:
python -m video.transmitir --cama-id cama-09 --dispositivo /dev/video2 --una-vez
```

**Política de identidad (ADR-020):**
- Cámara **con serial único** (p. ej. la capturadora `35562055`, o la WebCamera del
  banco `251735124`) → usa el serial: el runner la sigue aunque cambie de puerto USB,
  y su pin queda anclado al by-id (verificado en banco tras corregir la guarda de
  by-id compartido, que comparaba por identidad de objeto y anclaba al puerto).
- Webcam **sin serial** (las Jieli del banco: su by-id no trae serial) → usa el **puerto
  físico** (el fragmento del by-path de TU puerto — el de cama-09 está en la tabla de
  abajo) y **etiqueta físicamente el puerto**. Dos webcams idénticas comparten by-id:
  solo el puerto las distingue.
- Mantén una tabla puerto↔cama por Jetson (rellénala al instalar):

| Jetson | Puerto (by-path) | Etiqueta física | Cama |
|---|---|---|---|
| jetson-01 | `usb-0:2.3` | "CAMA 09" (pendiente etiquetar el puerto) | cama-09 |

En cada (re)lanzamiento el runner imprime el mapeo (`[cama-09] <- by-path ... -> rtsp://...`):
verifícalo al dar de alta una cama. Si el video de una cama "parpadea" entre dos cámaras,
hay **dos runners publicando el mismo `cama_id`** — revisa la tabla.

**Notas:** el runner reintenta para siempre si la cámara o la red se caen A MEDIA CORRIDA
(backoff hasta 30 s; la cama se ve desconectada en el dashboard, que es la verdad) y solo
se rinde ante un entorno roto (ffmpeg desinstalado o inmatable) o si un nodo literal pasa
a ser OTRA cámara. Ojo: en el **arranque** una identidad ausente/ambigua o no verificable
falla fuerte con exit 1 — el reintento indefinido aplica solo a media corrida, cuando ya
no hay un humano delante (matriz de ADR-020). Ajusta
`--fps` a lo que la webcam anuncie en MJPG (`v4l2-ctl --list-formats-ext -d /dev/videoN`);
si pides un framerate que no da, el driver lo cambia en silencio. Detener: Ctrl+C. **Como
servicio systemd (ADR-023)**: las units templated ya viven en el repo —
`video/video-transmitir@.service` y `ocr/ocr-publicar@.service`, con la config por cama en
`/etc/monitoreo/cama-NN.conf` (ejemplo: `docs/ito2/cama-09.conf.ejemplo`) — instalación en
la cabecera de cada unit y en `ocr/README.md` §Jetson. Con ellas ambos runners arrancan
solos al encender la Jetson y reviven ante cualquier salida (`systemctl stop` para
detener; un `kill -9` ya no detiene).

### 2.2 Caja negra local + bridge al server off-site (ADR-024, Fase 1)

El server es off-site y el enlace puede caerse: el edge persiste TODO localmente y el
live viaja por un bridge. **Orden de transición SIN pérdida** (cada paso es verificable
antes del siguiente; el OCR sigue publicando al server hasta el paso 4):

**Paso previo OBLIGATORIO — la app corregida en TODOS los teléfonos** (F1.1 + F1.2;
la versión sigue siendo 1.0.6: el APK se construye desde la rama del Front que ya
trae F1.2). El retained `monitoreo/edge/{device_id}/bridge` aparece en el server en el
**paso 1** (al arrancar el bridge), no en el flip — y la app anterior a la versión
**1.0.6** se congela con él (su hilo MQTT muere y sigue mostrando "Conectado" con
valores congelados). Antes del paso 1: **listar TODOS los teléfonos que tengan la app**
(no solo el de Dr. Milton), instalar el APK 1.0.6 en cada uno y **verificar en el
header de cada teléfono** que dice `v1.0.6`. Si falta uno, no se pasa al paso 1.

```bash
# 0) Reloj sincronizado (el recibido_en de la BD local ES la linea temporal
#    del historico y la que hereda el backfill de F2):
timedatectl   # debe decir "System clock synchronized: yes" (si no: revisar NTP)
#    (la app descarta vitales con ts a mas de 30 s de su reloj: un edge con
#    la hora mal se ve "--" en la app — falla cerrado)

# 0b) El clon de la Jetson AL DIA (los pasos 1 y 4 copian DESDE el clon: el
#     conf de F1 original no arranca y la unit vieja no trae After/Wants):
cd /home/jetson/MonitoreoPediatria && git pull && git log -1 --oneline
#   -> el commit de F1.2 o posterior (si git pull se queja de cambios locales:
#      PARAR y revisarlos, nunca forzar)
grep -c '^persistence_location' docs/ito2/mosquitto-edge.conf.ejemplo   # -> 0
grep -E '^(After|Wants)=' ocr/ocr-publicar@.service   # -> ambas con mosquitto.service

# 1) Broker local + bridge (el OCR AUN publica directo al server: cero
#    interferencia). mosquitto-clients trae mosquitto_sub (verificaciones) y
#    sqlite3 el conteo de filas del paso 5:
sudo apt install -y mosquitto mosquitto-clients sqlite3
#   Anotar la version instalada (Ubuntu 22.04 trae 2.0.11; la validacion de
#   F1.1 fue con 2.0.18 — la prueba del corte en banco valida ESTA version):
dpkg -s mosquitto | grep '^Version'   # -> 2.0.11-... (anotarla en PENDIENTES)
#   ANTES de copiar: el conf de FABRICA debe traer la persistencia (el nuestro
#   NO repite la ruta — repetirla impide arrancar):
grep -E '^persistence' /etc/mosquitto/mosquitto.conf
#   -> debe mostrar:  persistence true  Y  persistence_location /var/lib/mosquitto/
sudo cp docs/ito2/mosquitto-edge.conf.ejemplo /etc/mosquitto/conf.d/monitoreo-edge.conf
#   -> editar los DOS "jetson-01" al device_id de esta Jetson
sudo systemctl restart mosquitto && sudo systemctl enable mosquitto
#   Verificacion cuantitativa (las tres, antes del paso 2):
systemctl is-active mosquitto          # -> active
ss -ltn | grep ':1883'                 # -> SOLO 127.0.0.1:1883 (invariante de privacidad)
ls /etc/mosquitto/conf.d/              # -> solo monitoreo-edge.conf (+README): sin confs viejos

# 2) Verificar el bridge y la senal de enlace — correr EN el server
#    (ssh chuy@100.110.157.112):
#    mosquitto_sub -h localhost -t 'monitoreo/edge/#' -v   -> "... 1" (retained)

# 3) Ingesta local (pasos completos en la cabecera de la unit) — el mkdir va
#    SIN sudo: con sudo el directorio queda de root y el servicio
#    (User=jetson) no puede crear la BD:
mkdir -p /home/jetson/datos/monitoreo
cd /home/jetson/MonitoreoPediatria && \
  /home/jetson/miniforge3/envs/ocr-monitoreo/bin/python -m persistencia.ingerir \
  --bd /home/jetson/datos/monitoreo/vitales.db --solo-esquema
sudo cp persistencia/vitales-ingest-edge.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now vitales-ingest-edge

# 4) (por cama) El flip: BROKER=localhost en /etc/monitoreo/cama-NN.conf
#    *** NO tocar SERVIDOR_VIDEO: el video sigue directo a MediaMTX ***
#    Re-copiar la unit del OCR: la del repo ahora trae After/Wants=mosquitto
#    (depende del broker LOCAL); sin re-copiarla, eso nunca llega a la Jetson.
sudo cp ocr/ocr-publicar@.service /etc/systemd/system/
sudo systemctl daemon-reload
systemctl show -p After,Wants ocr-publicar@cama-NN | grep mosquitto
#   -> DOS lineas (After=... y Wants=...), ambas con mosquitto.service
sudo systemctl restart ocr-publicar@cama-NN

# 5) Verificar el mundo nuevo:
#    - app/dashboard en vivo como siempre (latencia indistinguible)
#    - filas creciendo en la BD LOCAL:
#      sqlite3 /home/jetson/datos/monitoreo/vitales.db "SELECT count(*), max(ts) FROM vitales;"
#    - y en la BD del SERVER (via bridge) igual que antes
# Rollback de un paso: revertir BROKER en el conf + restart de la unit.
```

**Prueba del corte** (la razón de todo esto): tirar el internet del edge >2 min con el
OCR ciclando (Mac dormida y despierta) → la BD local sigue creciendo TODO el corte; el
server muestra `monitoreo/edge/<device_id>/bridge = 0` (a los ~22 s de un corte
silencioso — keepalive del bridge de 15 s) y **la app marca esas camas "Sin conexión"
(punto ámbar) en ≤25 s** — en un corte silencioso pasa ANTES por "Sin datos" (punto gris
+ etiqueta) a los ~10–12 s, por el timeout de datos (F1.2): es lo esperado, no un
fallo. Al volver el enlace, la app queda al día en segundos y el estado retenido del
server converge con el local (`mosquitto_sub -v 'monitoreo/estado/#'` igual en ambos
lados). **Variante obligatoria**: devolver el enlace con el OCR en su fase offline
(Mac dormida) → la app NO muestra vitales como actuales (`--` gris con la etiqueta
"Sin datos"): el bridge re-entrega la última vital retenida y la app no la cuenta. (La
limitación del APAGÓN de la Jetson con el OCR sin poder arrancar — ADR-024 §4 — quedó
cerrada en la app por el timeout de datos: la cama se ve "Sin datos", nunca verde; el
estado retenido del server y la web aún ven el `online` viejo.) El hueco del server se rellena solo cuando
llegue la Fase 2 (reenviador); mientras, una copia manual de la BD local es material de
CONSULTA (adjuntarla aparte), **jamás** merge en la BD del server (sin dedup
duplicaría) — y solo hacia el server, nunca a laptops, borrando la copia tras usarla
(datos de menores, CONTEXT §2).

**Prueba del OCR congelado** (timeout de datos de la app, F1.2 — **jamás en una cama
con paciente**):

```bash
sudo systemctl kill -s STOP ocr-publicar@cama-NN
#   -> la app marca la cama "Sin datos" (punto gris + etiqueta) en <=13 s desde el
#      kill (nominal 10-12 s tras la ultima vital que mostro: 10 s de umbral + hasta
#      2 s del timer; el resto es latencia) y SIEMPRE antes de ~22 s, cuando llega el
#      offline del will del OCR (el STOP congela tambien su hilo MQTT); al llegar ese
#      offline, la cama sigue en "Sin datos". Si solo cambia a los ~22 s, el timeout
#      NO funciona.
sudo systemctl kill -s CONT ocr-publicar@cama-NN
#   -> se recupera sola en segundos (paho reconecta y re-publica online)
```

**Un proceso detenido sigue `active (running)`: systemd NO lo revive** (`Restart=always`
solo actúa si el proceso sale; la unit no tiene `WatchdogSec`). Mandar SIEMPRE el
`CONT` — o `sudo systemctl restart ocr-publicar@cama-NN`. Honestidad de la prueba: el
STOP congela también a paho, así que solo sus primeros ~22 s equivalen al OCR colgado
con proceso vivo (ADR-022 §6a); lo que prueba el timeout es que "Sin datos" aparezca
antes del will.

**Prueba del teléfono bloqueado** (reloj `CLOCK_BOOTTIME` de la app, F1.2): con la app
mostrando datos en vivo, bloquear el teléfono 1 min y desbloquear → o los valores ya se
actualizan cada ~1 s (la app puede seguir recibiendo bloqueada: tiene servicio en primer
plano), o aparece "Sin datos" en ≤2 s y se recupera sola; **NUNCA números fijos por más
de ~10 s**. Si se puede ver el log de la app, al arrancar dice `timeout de datos con
reloj CLOCK_BOOTTIME`.

**Corrida manual de depuración en la Jetson**: parar antes el servicio (`systemctl stop
vitales-ingest-edge`) y pasar `--bd` fuera del working tree — los defaults crearían otra
BD de datos de menores dentro del clon.

**Volumetría/disco**: ~70–90 MB/día/cama; el pruning llega en F2 — mientras tanto,
`df -h` en cada visita al banco.

---

## Parte 3 — Mando (Windows / visualizador)

Con Tailscale activo, abre en el navegador:
```
http://100.110.157.112:8080
```
Verás la cuadrícula de camas con datos en vivo y video.

Enlaces útiles para diagnóstico:
- Video directo de una cama: `http://100.110.157.112:8889/cama-01`
- Datos crudos (en el servidor): `mosquitto_sub -h localhost -t 'monitoreo/#' -v`

---

## Parte 4 — Generar y desplegar el dashboard (web Next.js)

El código de la web vive en `web/nextapp/` (proyecto Next.js). Se compila en una máquina con Node 20 (Windows o la Mac, no el Celeron) y se copian los archivos estáticos al servidor.

En la máquina de build (PowerShell en Windows):
```powershell
cd C:\Dev\Dr.Milton\MonitoreoPediatria\MonitoreoPediatria\web\nextapp
npm install        # solo la primera vez
npm run build      # genera la carpeta out/

# desplegar al servidor (limpio cada vez):
ssh chuy@100.110.157.112 "rm -rf ~/dashboard"
scp -r out chuy@100.110.157.112:~/dashboard
```
El servicio `dashboard` sirve esos archivos al instante (no hay que reiniciarlo).

---

## Orden de arranque

1. **Servidor**: los servicios (`mosquitto`, `mediamtx`, `dashboard`, `vitales-ingest`) arrancan solos al encender. Verifica: `systemctl status mosquitto mediamtx dashboard vitales-ingest --no-pager`.
2. **Edge real (Jetson)**: arranca solo al encender (units `ocr-publicar@` y `video-transmitir@`, ADR-023). Los primeros exits del OCR tras el boot (tailnet aún subiendo) son el comportamiento esperado — systemd reintenta cada 5 s hasta que conecta. Solo la fuente necesita manos: la Mac en modo espejo/SimCore encendida.
3. **Edge de simulación** (si se usa): conecta la webcam y lanza el simulador (Parte 2).
4. **Mando**: abre `http://100.110.157.112:8080`.

---

## Qué hacer cuando cambias código

### Cambias el simulador (Python, carpeta `simulador/`)
1. En Windows (donde editas): `git add -A && git commit -m "..." && git push`
2. En el edge (Mac): `cd ~/MonitoreoPediatria && git pull`
3. Relanza el simulador (Ctrl+C y vuelve a correr `python run.py ...`).

### Cambias la web (Next.js, carpeta `web/nextapp/`)
1. Edita (en Antigravity o a mano) y compila: `cd web/nextapp && npm run build`
2. Despliega al servidor: los dos comandos de la Parte 4 (`rm -rf ~/dashboard` + `scp -r out ...`).
3. Refresca el navegador. (No se necesita git para que funcione; el git es solo para respaldar el código fuente.)

### Cambias configuración del servidor (Mosquitto / MediaMTX)
- Edita el archivo de config en el servidor y reinicia ese servicio: `sudo systemctl restart mosquitto` (o `mediamtx`).

### Cambia la IP del servidor (raro, Tailscale es fija)
- Simulador: usa `--server <nueva-ip>` o cambia el default en `simulador/run.py`.
- Web: actualiza las variables `NEXT_PUBLIC_` en `web/nextapp` y **recompila** (las IPs se hornean en el build estático).

---

## Diferencia clave: código que se ejecuta vs. web compilada
- El **simulador** es código que se ejecuta en el edge → se reparte por **git** (push/pull).
- La **web** se compila a archivos estáticos → se despliega por **scp** (no necesita git para correr).

---

## Para el monitor real (futuro)
Cuando se integre el Mindray uMEC10/uMEC12:
- Se escribe un adaptador que lee el monitor por HL7/PDS y publica el **mismo** contrato (`monitoreo/vitales/{cama_id}`). Reemplaza al simulador de datos.
- El video del paciente sigue igual (webcam o, si se quiere, la captura HDMI del monitor) en `/cama-XX`.
- La web no cambia.
