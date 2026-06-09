# Fase 2 — Video en vivo (Femto Bolt → servidor → navegador)

```
[Mac + Femto] --RTSP--> [Servidor: MediaMTX] --WebRTC--> [Windows: navegador]
```

La Mac codifica el video y lo publica una vez; MediaMTX en el servidor lo reparte a quien se conecte.

## Parte A — Instalar MediaMTX en el servidor

Conéctate al servidor (`ssh chuy@100.110.157.112`) y ejecuta:

```bash
cd ~
mkdir -p mediamtx && cd mediamtx
wget https://github.com/bluenviron/mediamtx/releases/download/v1.17.0/mediamtx_v1.17.0_linux_amd64.tar.gz
tar -xzf mediamtx_v1.17.0_linux_amd64.tar.gz
./mediamtx
```

MediaMTX arranca con configuración por defecto: acepta publicación RTSP en el puerto **8554** y sirve WebRTC en el **8889**. Déjalo corriendo en esa terminal para la primera prueba.

Por defecto MediaMTX solo escucha conexiones de red; Tailscale las trae cifradas, así que el video viaja seguro entre las máquinas.

## Parte B — Instalar dependencias en la Mac

```bash
sudo apt install -y ffmpeg
source ~/orbbec_env/bin/activate
pip install opencv-python numpy   # si no estaban
```

## Parte C — Transmitir desde la Mac

```bash
cd ~/MonitoreoPediatria/capture
source ~/orbbec_env/bin/activate
python stream_to_server.py
```

Debe imprimir "Publicando en rtsp://100.110.157.112:8554/femto" y luego ir contando frames enviados.

## Parte D — Ver el video (desde Windows o cualquier navegador)

Abre en el navegador:

```
http://100.110.157.112:8889/femto
```

Deberías ver el video en vivo de la Femto con menos de ~1 segundo de retraso.

## Solución de problemas

| Problema | Solución |
|----------|----------|
| "ffmpeg se cerró" en la Mac | MediaMTX no está corriendo, o el puerto 8554 no es alcanzable. Verifica que `./mediamtx` siga activo. |
| El navegador no muestra video | Confirma la URL y el puerto 8889; revisa que el script siga enviando frames. |
| `ffmpeg: command not found` | `sudo apt install -y ffmpeg` en la Mac |
| Video entrecortado | Baja resolución/fps: `python stream_to_server.py --width 854 --height 480 --fps 20` |
| Mucha latencia | Verifica en `tailscale status` que la conexión Mac↔servidor sea `direct` y no `relay` |

## Siguientes pasos (después de validar)

- Dejar MediaMTX como servicio (systemd) para que arranque solo.
- Dejar el streaming de la Mac como servicio.
- Página web propia que embeba el video junto a los signos vitales (en vez de la URL cruda de MediaMTX).
