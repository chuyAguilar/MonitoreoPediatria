# Instalación en la laptop (MacBook Pro 2014 + Ubuntu)

Guía para dejar la laptop lista como estación de captura de la Femto Bolt.

## 1. Requisitos previos

- Ubuntu instalado y actualizado: `sudo apt update && sudo apt upgrade`
- La Femto Bolt conectada a un puerto **USB-A** de la laptop (ambos son USB 3.0 en la MBP 2014). Usa el cable original de la cámara.
- Fuente de poder de la Femto Bolt conectada (la cámara requiere su adaptador, no se alimenta solo por USB).

Verifica que el sistema vea la cámara:

```bash
lsusb | grep -i orbbec
```

Debe aparecer un dispositivo Orbbec. Si no aparece, prueba otro puerto/cable.

## 2. Dependencias del sistema

```bash
sudo apt install -y python3-venv python3-pip git
```

## 3. Entorno virtual + SDK

En Ubuntu 24.04+ pip exige entorno virtual (PEP 668):

```bash
python3 -m venv ~/orbbec_env
source ~/orbbec_env/bin/activate
pip install --upgrade pyorbbecsdk2 opencv-python numpy scipy
```

Verificación:

```bash
pip show pyorbbecsdk2 | grep Version
```

## 4. Reglas udev (permisos USB)

Sin esto, el SDK no puede abrir la cámara sin `sudo`:

```bash
# Encontrar la ruta del paquete instalado
python -c "import pyorbbecsdk, os; print(os.path.dirname(pyorbbecsdk.__file__))"

# Ejecutar el script de setup que instala las reglas udev
# (reemplaza la ruta con la salida del comando anterior)
python /ruta/del/paso/anterior/shared/setup_env.py
```

Después **desconecta y reconecta la cámara** para que apliquen las reglas.

## 5. Probar la captura

```bash
cd ~/MonitoreoPediatria   # o donde esté clonado el proyecto
source ~/orbbec_env/bin/activate
python capture/femtobolt_test.py
```

Debe abrirse una ventana con el video a color a la izquierda y el mapa de profundidad coloreado a la derecha. Presiona `S` para guardar una captura de prueba, `Q` para salir.

## Solución de problemas

| Problema | Solución |
|----------|----------|
| "No device found" | Reglas udev no instaladas (paso 4) o cámara sin alimentación |
| `ModuleNotFoundError: pyorbbecsdk` | Activar el venv: `source ~/orbbec_env/bin/activate` |
| Frames vacíos / timeout | Cambiar a otro puerto USB; verificar que sea USB 3.0 con `lsusb -t` (5000M) |
| Ventana no abre | Verificar OpenCV: `python -c "import cv2; print(cv2.__version__)"` |
| Cámara se desconecta sola | Cable de mala calidad o puerto sin suficiente energía; usar el cable original |

## Referencias

- Docs oficiales pyorbbecsdk v2: https://orbbec.github.io/pyorbbecsdk/
- Ejemplos oficiales: https://github.com/orbbec/pyorbbecsdk/tree/v2-main/examples
