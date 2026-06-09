# Hito 2 — Investigación de proyectos open source

Búsqueda de proyectos que ya hacen monitoreo de signos vitales por cámara (respiración / frecuencia cardiaca sin contacto), para no partir de cero y apoyarnos en lo que ya existe.

## Bucket A — Respiración por movimiento (lo más alineado al proyecto)

| Proyecto | Qué hace | Madurez / licencia | Encaje con nosotros |
|----------|----------|--------------------|---------------------|
| [michaelwwan/air-400](https://github.com/michaelwwan/air-400) | Estimación de respiración (forma de onda + RPM) en video de **infantes**. Dataset AIR-400, checkpoints e inferencia. Paper WACV 2026. | Activo, MIT. Deep learning (optical flow pyflow + YOLO ROI), pesado, orientado a GPU. Trabaja sobre **video grabado**, no stream en vivo. | Excelente como **referencia científica y validación**. Pesado para correr en vivo en el i5 sin GPU. |
| [cezius/Neonatal-Respiration-Monitoring-Algorithm](https://github.com/cezius/Neonatal-Respiration-Monitoring-Algorithm) | RPM de neonatos en UCIN desde RGB; CNN detecta ROI (panza/espalda) + análisis de movimiento. Paper MDPI Appl. Sci. 2021. | Pequeño, sin licencia clara, sin dataset (privado). Jupyter, sobre archivos HDF5. | Buena **referencia de algoritmo**; no es plug-and-play en vivo. |
| [kavehbc/KinRes](https://github.com/kavehbc/KinRes) | Graba señal respiratoria con cámara de **profundidad** (Kinect v2). | Windows, específico de Kinect. | Confirma el enfoque de profundidad; no reutilizable directo (otra cámara, otro SO). |

Papers de respaldo del enfoque de **profundidad** en infantes (no son código, son evidencia de que funciona): monitoreo sin contacto de patrón respiratorio en prematuros en incubadora con cámaras de profundidad, y estimación de volumen tidal con Kinect v2 (errores ~5-6 ml).

## Bucket B — Frecuencia cardiaca por color (rPPG)

| Proyecto | Qué hace | Notas |
|----------|----------|-------|
| [ubicomplab/rPPG-Toolbox](https://github.com/ubicomplab/rPPG-Toolbox) | Estándar de la academia (NeurIPS 2023). Muchos métodos (CHROM, POS, PhysNet, etc.) y datasets. | Pesado, orientado a GPU y a **rostros de adultos**. Menos validado en neonatos. |
| [phuselab/pyVHR](https://github.com/phuselab/pyVHR), [pavisj/rppg-pos](https://github.com/pavisj/rppg-pos), [prouast/heartbeat](https://github.com/prouast/heartbeat) | Implementaciones más ligeras de rPPG. | Útiles si después queremos estimar pulso por color. |

## Bucket C — Enfoque propio ligero (clásico, sin deep learning)
MediaPipe Pose para ubicar el tórax + leer la **profundidad** de la Femto en esa zona + procesamiento de señal (filtro pasa-banda 0.3–1.5 Hz, detección de picos) → frecuencia respiratoria + detección de apnea. Corre en tiempo real en el hardware actual, sin GPU, y es explicable ante médicos.

## Conclusión de la investigación
- Ninguno de los proyectos de deep learning corre en vivo en nuestro hardware (i5 sin GPU, servidor Celeron) ni usa la **profundidad**, que es la gran ventaja de la Femto Bolt.
- La profundidad da una señal de respiración más limpia que el color y funciona en penumbra (clave en UCIN).
- Recomendación: construir el **enfoque propio ligero (Bucket C)** para el Hito 2, usando air-400 y los papers de profundidad como referencia y meta de validación.
