# Reproducir el sistema desde cero (runbook)

Guía completa para montar el sistema del Hito 2 desde una instalación limpia, como si fuera a desplegarse junto a un monitor real. Indica **qué comando se corre en qué equipo**.

> En esta etapa el monitor se **simula**. Cuando llegue el monitor real (Mindray uMEC10), se reemplaza el simulador por un adaptador que publica el mismo contrato de datos; todo lo demás queda igual.

---

## Inventario de equipos

| Rol | Equipo | SO | Tailscale | Qué corre |
|-----|--------|----|-----------|-----------| 
| **Servidor** | Gateway (Celeron) | Ubuntu Server | `100.110.157.112` | Mosquitto (datos), MediaMTX (video), web estática |
| **Edge** | laptop / Raspberry por sala | Linux (Mint/Ubuntu) | `100.72.226.69` | Simulador: publica datos + transmite webcam |
| **Mando** | PC de visualización | Windows / cualquiera | `100.69.158.31` | Navegador para ver el dashboard |

Las tres se unen por **Tailscale** (misma cuenta). Las IPs `100.x` son fijas de Tailscale.

Puertos usados en el servidor: `1883` MQTT, `9001` MQTT-WebSocket, `8554` RTSP (entra el video), `8889` WebRTC (sale el video), `8080` web.

---

## Parte 0 — Red (en las 3 máquinas)

Instala Tailscale en cada equipo e inicia sesión con la **misma cuenta**:
- Linux: `curl -fsSL https://tailscale.com/install.sh | sh` y luego `sudo tailscale up`
- Windows: instalador de tailscale.com/download/windows

Verifica que se vean entre sí: `tailscale status` debe listar las tres.

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

Con esto, los tres servicios del servidor arrancan solos al encender la máquina.

---

## Parte 2 — Edge (la máquina con la(s) webcam(s))

Conéctate: `ssh chuy@100.72.226.69`

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git ffmpeg
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

1. **Servidor**: los servicios (`mosquitto`, `mediamtx`, `dashboard`) arrancan solos al encender. Verifica: `systemctl status mosquitto mediamtx dashboard --no-pager`.
2. **Edge**: conecta la webcam y lanza el simulador (Parte 2).
3. **Mando**: abre `http://100.110.157.112:8080`.

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
