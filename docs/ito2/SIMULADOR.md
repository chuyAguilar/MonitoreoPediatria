# Simulador de monitores — guía de uso

Simula uno o varios monitores de signos vitales (formato del contrato, ver `CONTRATO_DATOS.md`) y, opcionalmente, transmite el video de webcams reales conectadas a la máquina. Pensado para desarrollar la web sin tener el monitor real.

Código en `simulador/`:
- `signos.py` — genera los signos vitales neonatales que varían en el tiempo.
- `camaras.py` — detecta las webcams conectadas.
- `video.py` — transmite una webcam por RTSP al servidor.
- `run.py` — lanzador interactivo que une todo.

## Requisitos

**En el servidor — broker MQTT (Mosquitto):**

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo tee /etc/mosquitto/conf.d/monitoreo.conf >/dev/null <<'EOF'
listener 1883
protocol mqtt
listener 9001
protocol websockets
allow_anonymous true
EOF
sudo systemctl restart mosquitto
```

Esto abre MQTT en el puerto **1883** (para el simulador) y MQTT-sobre-WebSocket en el **9001** (para la web). `allow_anonymous true` es solo para desarrollo; en producción se añade usuario/contraseña.

> Y MediaMTX debe estar corriendo en el servidor para el video (igual que en el Hito 1: `cd ~/mediamtx && ./mediamtx`).

**En la máquina que captura (la Mac):**

```bash
source ~/orbbec_env/bin/activate
pip install paho-mqtt
# opencv y ffmpeg ya están instalados del Hito 1
```

## Uso

Trae el código y ejecuta el lanzador interactivo:

```bash
cd ~/MonitoreoPediatria && git pull
cd simulador
source ~/orbbec_env/bin/activate
python run.py
```

Te va a (1) detectar las cámaras conectadas y preguntar cuántas usar, (2) preguntar cuántas camas simular, y (3) arrancar. Las primeras camas reciben el video de las webcams; las demás solo datos.

### Opciones (no interactivo / pruebas)

```bash
python run.py --camas 4 --camaras 2          # 4 camas, 2 con video
python run.py --camas 3 --sin-video          # solo datos, sin video
python run.py --camas 2 --sin-video --solo-consola   # imprime JSON, sin broker (prueba rápida)
python run.py --camas 4 --server 100.110.157.112     # IP del servidor (broker + RTSP)
```

| Opción | Para qué |
|--------|----------|
| `--camas N` | cuántas camas simular |
| `--camaras K` | cuántas webcams usar (máx. las detectadas) |
| `--server IP` | servidor (broker MQTT + RTSP). Default `100.110.157.112` |
| `--sin-video` | no transmitir video |
| `--solo-consola` | imprime el JSON en pantalla en vez de MQTT (no necesita broker) |
| `--hz` | frecuencia de datos (default 1/s) |
| `--ancho/--alto/--fps` | resolución y cuadros del video |

## Verificar que llega

**Datos** — en el servidor, suscríbete a los temas:

```bash
mosquitto_sub -h localhost -t 'monitoreo/#' -v
```

Debes ver los mensajes de cada `monitoreo/vitales/cama-XX`.

**Video** — en el navegador: `http://100.110.157.112:8889/cama-01`

## Notas
- El simulador publica con *retención*: la web verá el último valor apenas se conecte.
- Cada cama usa el mismo `cama_id` para datos (`monitoreo/vitales/cama-01`) y video (`/cama-01`).
- El día que llegue el monitor real, se reemplaza el simulador por un adaptador HL7/PDS que publique el mismo formato; la web no cambia.
