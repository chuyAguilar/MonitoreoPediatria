# DECISIONS — Registro de Decisiones de Arquitectura (ADRs)

> Por qué el sistema está hecho como está. Cada entrada es un ADR: contexto, decisión y
> consecuencias. Para el *cómo* ver [`ARCHITECTURE.md`](ARCHITECTURE.md); para reglas y
> estado ver [`CONTEXT.md`](CONTEXT.md).
>
> **Estado:** `Aceptada` (vigente) · `Reemplazada` (ya no se aplica) · `Propuesta` (sin cerrar).

| # | Decisión | Estado |
|---|---|---|
| ADR-001 | Fuente de datos intercambiable por contrato | Aceptada |
| ADR-002 | Captura por video + OCR (no egress digital) | Aceptada |
| ADR-003 | Contrato `1.1`: `origen: ocr` + `confianza` opcional | Aceptada |
| ADR-004 | Jetson Orin Nano como edge | Aceptada |
| ADR-005 | MQTT (Mosquitto) para vitales | Aceptada |
| ADR-006 | MediaMTX + RTSP/WebRTC (WHEP) para video | Aceptada |
| ADR-007 | `cama_id` como clave de unión datos↔video | Aceptada |
| ADR-008 | Web Next.js export estático, auto-alojada | Aceptada |
| ADR-009 | Red privada Tailscale | Aceptada |
| ADR-010 | Cámaras normales por cama (no profundidad) | Aceptada |
| ADR-011 | Simulador conservado como banco de pruebas | Aceptada |
| ADR-012 | Adaptador HL7/PDS del monitor real | Reemplazada |
| ADR-013 | OCR iteración 1: motor de plantilla + perfiles ROI en JSON | Aceptada |
| ADR-014 | El motor de plantilla no sirve con tipografía real: hace falta OCR de verdad | Aceptada |
| ADR-015 | Perfiles: signo ausente y campos combinados (PNI `SIS/DIA`) | Aceptada |
| ADR-016 | Motor OCR de producción: PaddleOCR, con entrada cruda al motor | Reemplazada (motor) |
| ADR-017 | Paddle Inference segfaultea en aarch64: producción pasa a RapidOCR/ONNX Runtime | Aceptada |
| ADR-018 | Capturadora por identidad estable (serial/by-id) con fail-hard, no por índice | Aceptada |
| ADR-019 | Dashboard: video a demanda + política de conexión WebRTC (ICE sin internet, gracia) | Aceptada |
| ADR-020 | Video por cama: runner supervisado con identidad estable (x264 software, watchdog de progreso) | Aceptada |

---

## ADR-001 — Fuente de datos intercambiable por contrato

**Estado:** Aceptada (jun 2026, reforzada jul 2026)

**Contexto.** El dato del signo vital podía venir de fuentes muy distintas (simulador, monitor
digital, OCR) y esas fuentes cambiarían con el tiempo. No queríamos reescribir el servidor ni
la web cada vez.

**Decisión.** Definir un **contrato JSON** (ver `docs/ito2/CONTRATO_DATOS.md`) contra el cual
se construye la web. La fuente que publica ese contrato es intercambiable. Cualquier productor
que emita el contrato por MQTT es válido.

**Consecuencias.** (+) El cambio de paradigma jun→jul (de digital a OCR) **no tocó** servidor ni
web. (+) Se puede correr simulador y OCR indistintamente. (−) Hay que disciplinar cambios del
contrato con versionado (ADR-003).

---

## ADR-002 — Captura por video + OCR en lugar de egress digital

**Estado:** Aceptada (jul 2026) — reemplaza el enfoque de ADR-012

**Contexto.** El plan original era sacar los signos del monitor Mindray uMEC10 por su salida
digital (HL7 v2.3.1 / PDS sobre TCP). Eso depende de: que el puerto esté habilitado, que PDS
esté licenciado/activo, y posiblemente middleware eGateway. Es específico de marca/modelo y no
generaliza a monitores de otros fabricantes en un hospital heterogéneo.

**Decisión.** Obtener los signos **leyendo la pantalla del monitor con OCR**: la salida HDMI del
monitor entra por una **capturadora** en la Jetson, y un pipeline de visión reconoce los
números.

**Consecuencias.**
- (+) **Agnóstico de marca/modelo:** funciona con cualquier monitor que tenga salida de video.
- (+) No requiere licencias ni protocolos propietarios del fabricante.
- (+) No intrusivo: no se conecta nada al monitor clínico salvo un cable de video.
- (−) El OCR **puede leer mal** → obliga a validar rango + reportar confianza (ADR-003).
- (−) Más carga de cómputo en el edge que un simple parse de HL7 → motiva la Jetson (ADR-004).
- (−) Depende del layout de la pantalla; cambiar de modelo de monitor exige reajustar regiones.

---

## ADR-003 — Contrato `1.1`: `origen: "ocr"` + `confianza` opcional

**Estado:** Aceptada (jul 2026)

**Contexto.** Con OCR, una lectura errónea (p. ej. un "180" fantasma por reflejo o parpadeo) no
debe presentarse igual que una lectura sólida. El simulador nunca necesitó esto.

**Decisión.** Subir el contrato a **`1.1`**, cambio **compatible hacia atrás**:
- `origen` puede valer `"ocr"` (además de `"simulador"` / `"umec10"`).
- Cada signo puede llevar un campo **`confianza` (0–1) opcional**.

**Consecuencias.** (+) La web actual **ignora** `confianza` → no se rompe nada hoy. (+) Deja la
puerta abierta a que la web resalte lecturas dudosas en el futuro. (−) El pipeline OCR debe
producir un score de confianza real, no un valor fijo.

**Alternativa descartada.** Mantener `1.0` idéntico sin confianza: más simple, pero perdería la
señal de calidad justo cuando la fuente pasa a ser falible.

---

## ADR-004 — Jetson Orin Nano como edge

**Estado:** Aceptada (jul 2026)

**Contexto.** El nuevo edge debe correr OCR sobre video **y** encodear varias cámaras a la vez,
por varias camas. Una Raspberry Pi o una laptop vieja se quedan cortas para inferencia de visión
en tiempo real.

**Decisión.** Usar **Jetson Orin Nano** (GPU con aceleración CUDA/TensorRT) como edge. Cada
Jetson cubre **N camas**; se escala añadiendo Jetsons.

**Consecuencias.** (+) GPU local para OCR/visión sin saturar CPU. (+) Encode por hardware para el
video. (−) Costo/unidad mayor que una Raspberry. (−) Ecosistema JetPack/L4T con versiones de
CUDA/OpenCV específicas → cuidar compatibilidad de librerías.

---

## ADR-005 — MQTT (Mosquitto) para los signos vitales

**Estado:** Aceptada (jun 2026)

**Contexto.** Muchos edges publicando datos de muchas camas hacia un servidor y una web que
consume en tiempo real.

**Decisión.** Transportar las vitales por **MQTT** con **Mosquitto** en el servidor
(`1883` mqtt, `9001` websockets). Topics `monitoreo/vitales/{cama_id}` y
`monitoreo/estado/{cama_id}`, QoS 1 y **retained**. La web habla MQTT sobre WebSocket.

**Consecuencias.** (+) Modelo pub/sub encaja con N publicadores. (+) `retained` = la web ve el
último valor apenas conecta. (+) La web descubre camas suscribiéndose a `monitoreo/vitales/+`.
(−) Broker es una pieza más que operar. (−) `allow_anonymous true` es solo para desarrollo;
producción necesita auth (ver `CONTEXT.md`).

**Alternativa descartada.** WebSocket propio: más código de servidor, sin retención ni fan-out
gratis.

---

## ADR-006 — MediaMTX + RTSP/WebRTC (WHEP) para el video

**Estado:** Aceptada (jun 2026)

**Contexto.** Video en vivo de baja latencia por cama, visible en el navegador sin plugins.

**Decisión.** El edge empuja cada cámara por **RTSP** a **MediaMTX** (`8554`), que lo re-sirve
por **WebRTC (WHEP)** (`8889`). El servidor **no transcodifica** (hardware Celeron limitado).

**Consecuencias.** (+) <1 s de latencia en el navegador (validado en Hito 1). (+) Un solo
destino para el mando. (−) `404` en WHEP significa "aún no hay publisher" → la web reintenta cada
5 s (`WHEP_RETRY_MS`). (−) Sin transcodificar, la calidad/lag dependen de lo que emita el edge.

---

## ADR-007 — `cama_id` como clave de unión datos↔video

**Estado:** Aceptada (jun 2026)

**Contexto.** Cada cama tiene datos (MQTT) y video (WebRTC) por caminos distintos; la web debe
unirlos sin ambigüedad y descubrir camas dinámicamente.

**Decisión.** El **`cama_id`** es a la vez el sufijo del topic MQTT **y** el nombre del stream en
MediaMTX. Para `cama-01`: datos en `monitoreo/vitales/cama-01`, video en `/cama-01`.

**Consecuencias.** (+) La web arma cada tarjeta con solo el `cama_id`. (+) Añadir una cama no
requiere configurar la web. (−) Disciplina de nombres obligatoria (`cama-NN`, dos dígitos).

---

## ADR-008 — Web Next.js export estático, auto-alojada

**Estado:** Aceptada (jun 2026)

**Contexto.** La web se prototipó en HTML plano (con Antigravity) y creció; se quería mantenible
y desplegable en un hospital **sin internet**.

**Decisión.** Migrar a **Next.js 15** (App Router, TS, `output: 'export'`) y **auto-alojar** el
build estático (`out/`) en el servidor vía systemd (`python3 -m http.server 8080`). **No Vercel.**
La SPA habla directo a Mosquitto y MediaMTX; sin backend por ahora. Config por `NEXT_PUBLIC_*`.

**Consecuencias.** (+) Sin dependencia de internet ni de Vercel. (+) Evita el bloqueo de contenido
mixto (HTTPS→ws/http) al servir todo por http en la red privada. (−) El build conviene hacerlo en
Windows/Mac (más potentes) y copiar `out/` al Celeron. (−) Sin backend, no hay auth ni
persistencia todavía.

---

## ADR-009 — Red privada Tailscale

**Estado:** Aceptada (jun 2026)

**Contexto.** Servidor, edges y mando pueden estar en redes físicas distintas; el tráfico
(video + datos de pacientes) no debe ir por internet abierto.

**Decisión.** Unir todas las máquinas en una **tailnet** (WireGuard). Direcciones `100.x` estables
entre máquinas.

**Consecuencias.** (+) Cifrado extremo a extremo y direccionamiento estable sin abrir puertos.
(−) Depende del coordinador de Tailscale; para un despliegue 100% offline habría que evaluar
Headscale o VPN propia.

---

## ADR-010 — Cámaras normales por cama (no profundidad)

**Estado:** Aceptada (jun 2026)

**Contexto.** La cámara de profundidad Orbbec Femto Bolt es pesada (USB3 + encode) y cara; para
el video de vigilancia por cama no hace falta profundidad.

**Decisión.** Usar **cámaras/webcams normales**, una por cama. La Femto se reserva para camas que
a futuro requieran respiración por profundidad + IA.

**Consecuencias.** (+) Edge más ligero, más camas por Jetson. (−) Sin dato de profundidad hasta
que se reintroduzca la Femto donde se necesite.

---

## ADR-011 — Simulador conservado como banco de pruebas

**Estado:** Aceptada (jul 2026)

**Contexto.** Con el paso a OCR, el simulador dejó de ser la fuente de producción. Pero permite
probar servidor + web **sin** montar Jetson/capturadora/monitor.

**Decisión.** **Conservar** `simulador/` como herramienta de desarrollo/prueba. Emite el mismo
contrato, así que es un sustituto válido del OCR para validar la web.

**Consecuencias.** (+) Se puede desarrollar la web sin hardware. (+) Sirve de referencia del
contrato. (−) Hay que mantenerlo alineado si el contrato evoluciona.

---

## ADR-012 — Adaptador HL7/PDS del monitor real

**Estado:** Reemplazada por ADR-002 (jul 2026)

**Contexto.** Se planeó un traductor HL7 v2.3.1 / Mindray PDS → contrato JSON, leyendo el monitor
uMEC10 por su salida digital.

**Decisión (original).** Adaptador que consumiera PDS/MLLP y publicara el contrato.

**Por qué se reemplazó.** Depende de licencias/middleware y no generaliza a otros monitores; el
enfoque OCR (ADR-002) es agnóstico de marca. **No se descarta del todo**: si en alguna cama el
egress digital está disponible y es confiable, un adaptador HL7 sigue siendo una fuente válida del
mismo contrato (por ADR-001). Queda como opción, no como camino principal.

---

## ADR-013 — OCR iteración 1: motor de plantilla + perfiles ROI en JSON

**Estado:** Aceptada (jul 2026)

**Contexto.** Primera iteración del módulo `ocr/` (offline, imagen fija → contrato 1.1).
Había que elegir un motor OCR para arrancar **sin muestra real del monitor** (se comparó
PaddleOCR, Tesseract y un lector de plantilla/7-segmentos), un formato para los perfiles de
ROI, y una política de validación de rangos coherente con `CONTEXT.md` §1.

**Decisión.**
1. **Motor de arranque: lector de plantilla de dígitos 7-segmentos** (OpenCV puro,
   `ocr/motor/plantilla.py`). Cero dependencias nuevas, determinista, y con confianza real y
   explicable (índice de Jaccard contra el atlas de dígitos). **Es andamiaje de la
   iteración 1**: valida el pipeline contra la imagen mock, y **probablemente será
   reemplazado en producción** (candidato principal: PaddleOCR sobre la GPU de la Jetson)
   cuando exista muestra real del monitor. Lo que garantiza que ese reemplazo no toque el
   resto del módulo es la **interfaz `LectorOCR`** (`ocr/motor/base.py`): perfiles,
   preprocesamiento, validación y contrato solo conocen la interfaz, no el motor.
2. **Perfiles de ROI en JSON** (no YAML): mismo formato que el contrato, `json` es stdlib
   (cero dependencias) y los perfiles pueden derivarse por código (el del mock se genera con
   `ocr/mock/generar_mock.py`; un test verifica que el archivo no se desincronice).
3. **Validación por rangos de PLAUSIBILIDAD FISIOLÓGICA, no por los "típicos" del
   contrato.** El "rango neonatal típico" de `CONTRATO_DATOS.md` (p. ej. FC 120–160) es
   **descriptivo** — documenta qué valores son normales. La validación OCR usa rangos
   **amplios** definidos en el perfil (p. ej. FC 50–250) cuyo único fin es descartar basura
   de lectura (una FC de 999 por dígito fantasma). **No son lo mismo**: anular todo lo que
   salga del rango típico ocultaría valores anormales pero reales (una bradicardia de
   80 lpm) justo cuando más importan (`CONTEXT.md` §1: un neonato en UCI siempre tendrá
   lecturas atípicas). Lo "típico" queda para la futura lógica de alarmas.

**Reglas de seguridad asociadas.** Valor no reconocido, con confianza baja o fuera del rango
de plausibilidad → `null` + `confianza 0` (nunca inventar un número). La PNI se emite
completa (sis/dia/media) o `null`: una tensión parcial es clínicamente engañosa.

**Consecuencias.** (+) El pipeline completo es testeable hoy, offline y sin hardware (34
tests contra el mock). (+) Cambiar de motor es implementar una clase. (−) El motor de
plantilla solo demuestra el pipeline, no la robustez ante monitores reales: la decisión del
motor de producción queda **pendiente de la muestra real** (se registrará en un ADR nuevo).
(−) El mock y el motor comparten el render de dígitos (`ocr/digitos.py`): los tests validan
integración, no reconocimiento en condiciones adversas.

**Seguimiento (jul 2026).** La muestra real llegó y confirmó el límite anticipado aquí: ver
**ADR-014**. El motor de plantilla queda como andamiaje de desarrollo; no es candidato de
producción.

---

## ADR-014 — El motor de plantilla no sirve con tipografía real: hace falta OCR de verdad

**Estado:** Aceptada (jul 2026)

**Contexto.** ADR-013 dejó anotado que el motor de plantilla 7-segmentos solo se había
probado contra dígitos que el propio módulo dibujaba (circularidad), y que la decisión del
motor de producción esperaba a una muestra real. La iteración 2 aportó esa muestra: un frame
de **SimCore** (simulador de monitor en navegador, 1920×1080), que es el banco de pruebas de
la capturadora. Sus números están dibujados con una **tipografía sans-serif proporcional**
(tipo Helvetica), no con un display de 7 segmentos.

**Medición.** ROIs calibradas y verificadas una a una (cada recorte contiene solo su número,
sin etiquetas ni unidades). Sobre los 17 glifos del frame:

| | Aciertos | Nota |
|---|---|---|
| Motor actual (redimensiona el glifo a la caja de la plantilla) | **5/17** | 2 de los 5 son "1" acertados por sesgo, no por reconocimiento |
| Variante diagnóstica con relación de aspecto preservada | **5/17** | corrige el sesgo pero no mejora el resultado |

Lecturas por signo: `74`→`11`, `98`→`11`, `14`→`11`, `36.8`→`11.1`, `120/75`→`111/11`,
`MAP 90`→`90` (único correcto, con margen de 0.04 sobre el segundo candidato, es decir azar).

**Dos causas, y la segunda es la que manda.**
1. *Sesgo del emparejador:* redimensionar cada glifo a la caja de la plantilla destruye la
   relación de aspecto, y la plantilla del `1` (una barra que al recortarse es un rectángulo
   sólido) se convierte en un atractor universal. Por eso casi todo se leyó como `1`.
2. *Incompatibilidad de alfabetos:* el experimento con aspecto preservado **mantiene 5/17**;
   solo cambia el atractor de `1` a `8`. Los márgenes entre el primer y el segundo candidato
   caen a 0.01–0.04, es decir, azar. **Arreglar la causa 1 no rescata el enfoque**: el
   alfabeto de 7 segmentos sencillamente no describe una tipografía sans-serif.

**Decisión.** Dar por cerrada la vía del motor de plantilla para producción. Se mantiene en
el repo como **andamiaje de desarrollo** (es lo que hace testeable el módulo sin hardware) y
el test de aceptación del frame real queda como `xfail(strict=True)`: el día que entre un
motor capaz, el test pasará y `strict` lo convertirá en error, forzando a retirar la marca.
**No se afinaron umbrales ni el atlas para "aprobar" este frame**, porque ajustar el motor a
una muestra concreta reproduce exactamente la circularidad que ADR-013 señaló.

La evaluación de **PaddleOCR** (candidato principal, con la GPU de la Jetson) queda como
iteración propia y ADR aparte.

**Lo que sí funcionó, y que sobrevive al cambio de motor.** El resto del pipeline se comportó
bien sobre datos reales: la segmentación de glifos fue correcta en los 6 campos; el separador
`/` se reconoció con el mejor margen de toda la medición (0.824, +0.461 sobre el segundo),
porque una diagonal es geométricamente distintiva con cualquier tipografía; y la calibración
de ROIs quedó verificada. Solo falla la identidad del dígito.

**Consecuencia clínica, que es lo importante.** Con lecturas equivocadas en la entrada, el
módulo **no publicó ni un solo valor erróneo**: todos los signos salieron `null` y la PNI
entera `null`. Las dos salvaguardas hicieron su trabajo (rango de plausibilidad + umbral de
confianza). Pero el margen fue mínimo y conviene dejarlo escrito: la FR se leyó como `11`
(real 14) con confianza **0.599** frente a un umbral de **0.600**. Una milésima separó al
sistema de publicar una frecuencia respiratoria falsa. Es la mejor evidencia de que la
defensa en profundidad es necesaria — y de que no basta con ella: hace falta un motor que
lea bien.

---

## ADR-015 — Perfiles: signo ausente y campos combinados (PNI `SIS/DIA`)

**Estado:** Aceptada (jul 2026)

**Contexto.** El layout real de SimCore rompió dos supuestos del perfil de la iteración 1:
no muestra **frecuencia de pulso** (el perfil exigía ROI para los 8 signos del contrato), y
presenta la presión como un **campo combinado** `120/75` con la media aparte (`MAP 90`), en
vez de tres números independientes.

**Decisión.** Extender el esquema del perfil con campos **opcionales y aditivos**, de modo
que un perfil de la iteración 1 siga siendo válido sin tocarlo:

- `"presente": false` — el monitor no muestra ese signo. No lleva ROI y el lector lo emite
  como `null` + confianza 0 **sin intentar OCR**.
- `"separador"` + `"parte"` — el signo se lee de un campo combinado: dos signos comparten
  ROI y se quedan con distinta mitad del texto (`parte` 0 o 1). El ROI se lee **una sola
  vez** (caché), así sistólica y diastólica provienen siempre de la misma lectura.

La partición vive en `lector.py`, no en el motor: cualquier motor real devuelve `"120/75"`
como texto de forma natural, así que la lógica **sobrevive al cambio de motor** (mismo
argumento que justifica la interfaz `LectorOCR`). El motor de plantilla añadió el glifo `/`
solo para poder producir ese texto.

**Consecuencias.** (+) `monitor_mock.json` sigue válido sin cambios y los 34 tests de la
iteración 1 siguen pasando. (+) La regla PNI todo-o-nada se refuerza gratis: si el motor no
reconoce el separador, el texto no tiene dos componentes y la presión entera sale `null` —
leer `"12075"` como una presión sería justo el número inventado que el módulo no debe
producir. (−) Hoy solo se soportan campos de **dos** componentes; un monitor que muestre
`sis/dia (media)` en un solo campo necesitaría extender el esquema.

### Salvaguardas añadidas tras la revisión adversarial

Una revisión multi-agente del código de esta iteración encontró varias formas de publicar un
dato erróneo que las reglas existentes no cubrían. Todas se cerraron y quedaron fijadas con
tests; el patrón común es que **cada número era plausible por separado y el conjunto
imposible**, o que una salvaguarda se podía desactivar sin que nada avisara.

1. **PNI incoherente** (`contrato.py`). Los rangos de sis, dia y media se solapan mucho, así
   que un solo dígito mal leído producía tríos como `40/75` con media 90 (diastólica y media
   por encima de la sistólica) o una presión invertida `75/120`, emitidos con confianza alta.
   Ahora se exige orden fisiológico (`dia < sis` y `dia ≤ media ≤ sis`, con 2 mmHg de holgura
   por el redondeo de la media). La regla pasa a ser **"ni parcial ni incoherente"**.
2. **Número truncado** (`preproceso.py` + `lector.py`). Una ROI fija calibrada para `120/75`
   corta el último dígito si el monitor pasa a `120/100`, y `"120/10"` sigue pareciendo una
   presión válida: publicaría shock en un paciente hipertenso. Ahora, si la tinta toca el
   borde de su caja, la lectura se descarta. Es la salvaguarda que convierte la limitación de
   las ROIs fijas en pérdida de dato en vez de dato falso.
3. **ROIs que se pisan** (`perfiles.py`). Dos signos apuntando al mismo sitio publican el
   mismo número como si fueran mediciones independientes. Es peor entre FC y FP, porque su
   concordancia es el control de calidad del oxímetro: una copia "concuerda" siempre. Se
   detecta **solapamiento**, no igualdad exacta (un píxel de diferencia leía lo mismo y
   evadía la comprobación).
4. **Partes invertidas** (`perfiles.py`). Intercambiar `parte` entre `pni_sis` y `pni_dia`
   daba `75/120` sobre una pantalla que mostraba `120/75`, y pasaba los rangos por solaparse.
   Ahora el perfil no carga.
5. **Confianza fuera de dominio** (`lector.py`). El umbral se aplica como `confianza <
   umbral`, así que un motor con escala 0–100 o que devolviera `NaN` lo habría atravesado
   entero, **desactivando la salvaguarda principal en silencio**. Se valida el dominio [0,1]
   y se rechaza lo que no cumpla. Deliberadamente **no se recorta**: convertir un 7.5 en 1.0
   haría pasar por óptima la peor lectura posible. Importa porque el motor de producción
   (ADR-014) aún está por enchufar.

**Limitación conocida de las ROIs fijas.** Están calibradas sobre un frame concreto. Con
texto alineado a la izquierda y la unidad pegada a la derecha (`SpO2 98 %`, `120/75 mmHg`),
un valor con un dígito más no cabe en la caja. Gracias a la salvaguarda 2 eso produce `null`,
no un número falso, pero **se pierde el signo**. Es el límite más serio de este perfil y hay
que revisarlo en la iteración 3 con capturas en vivo, donde el valor cambia solo.

---

## ADR-016 — Motor OCR de producción: PaddleOCR, con entrada cruda al motor

**Estado:** Reemplazada **en la elección del motor** por ADR-017 (ago 2026). La
**metodología de evaluación** (medir lectura + comportamiento en el fallo sobre el frame
real, con el fallo pesando más que el acierto), la decisión de **entrada cruda al motor**
y la política del **default que falla fuerte** siguen plenamente vigentes.

**Contexto.** ADR-014 cerró la vía del motor de plantilla para producción y dejó el test de
aceptación del frame real en `xfail`. Esta iteración elige e integra el motor de producción,
medido contra el mismo frame de SimCore, para que el módulo lea de verdad.

**Evaluación** (`ocr/herramientas/evaluar_motores.py`, reproducible). Se midió sobre las ROIs
del frame de SimCore, alimentando a cada motor el recorte crudo y variantes de
preprocesamiento. Métrica principal: lectura correcta **y** comportamiento en el fallo (que no
invente) — este último pesa más que el acierto bruto (`CONTEXT.md` §1).

| Motor | Lectura limpia | Robustez (9 frames transformados) | Comportamiento en el fallo | Coste |
|---|---|---|---|---|
| **PaddleOCR** (PP-OCRv6 rec) | **6/6**, confianza ~1.0 en toda variante | **9/9 correctos, 0 valores falsos** | En ROI no numérica lee las **letras** → el filtro numérico las descarta; no alucina dígitos | ~1.6 s/frame CPU; dep. pesada; descarga modelo |
| EasyOCR (PyTorch) | 6/6, pero confianza depende del preproceso (`temp` 0.536 < umbral en crudo/gris) | 6/9 correctos, **0 valores falsos** (suelta lecturas bajo blur/brillo) | Inventó `188` de "NIBP" con confianza 0.163 (el umbral lo filtra, por poco) | ~0.6 s/frame; dep. media (torch ya presente) |
| Tesseract | no evaluado | — | — | binario de sistema **no disponible** en el entorno de dev Windows |

**Decisión: PaddleOCR** (`ocr/motor/paddle.py`), usando su modelo de **reconocimiento de
línea** (`TextRecognition`), no la tubería con detección: las ROIs ya aíslan una línea. No es
un empate — PaddleOCR gana por lectura y robustez —, así que la regla de desempate
(offline/Jetson, sesgo a ONNX) no llega a aplicarse. Los tres motores superan de largo al de
plantilla (5/17). Tesseract quedó como referencia y no se pudo medir (falta el binario del
sistema en el dev de Windows); no era finalista.

**Por qué PaddleOCR sobre EasyOCR (ambos leen 6/6):**
- **Robustez:** 9/9 frente a 6/9 sobre frames perturbados (blur, brillo, contraste, ruido,
  reescala). Ambos con **cero valores falsos** — la métrica que más pesa —, pero PaddleOCR
  además no pierde lecturas.
- **Confianza:** uniforme (~1.0) sin depender del preprocesamiento; con EasyOCR, `temp` caía
  por debajo del umbral en varias variantes (lectura correcta pero descartada).
- **Fallo más seguro:** ante una ROI con letras, PaddleOCR lee las letras (y el filtro
  numérico las rechaza por construcción) en vez de forzar una interpretación en dígitos;
  EasyOCR alucinó un número, salvado solo por el umbral.

**Entrada cruda al motor (cambio de la interfaz).** Hasta ahora el lector entregaba al motor
una imagen **binarizada** (Otsu + normalización). Un OCR real rinde mucho peor sobre esa
binaria: se entrena con texto antialias. Desde esta iteración el lector entrega a **todos**
los motores el **recorte crudo** (color) y cada motor preprocesa a su gusto. La **firma** de
`LectorOCR.leer(imagen)` no cambia; cambia la *semántica* de `imagen`. El motor de plantilla
binariza internamente, así que su salida queda **byte-idéntica** (verificado por regresión
sobre el contrato del mock). Las **salvaguardas siguen en el lector**: la binaria se sigue
calculando para la guarda de borde y el chequeo de contraste. El adaptador de PaddleOCR
solo quita espacios del texto y **no recorta caracteres no numéricos**: si el modelo leyera
`1O2` (una `O` por un cero), dejar la letra hace que el lector lo rechace entero en vez de
convertirlo en un `12` truncado — la regla de oro manda.

**Dependencia opcional, motor por defecto que falla fuerte.** `paddleocr`/`paddlepaddle` van
en `ocr/requirements-motor.txt`, **no** en el `requirements.txt` del repo, con import
perezoso: importar `ocr` o correr el andamiaje nunca los arrastra. `lector.motor_por_defecto()`
usa PaddleOCR y **falla fuerte** si no está instalado (lanza con un mensaje accionable), en
vez de caer en silencio al andamiaje: un sistema de monitoreo que no puede leer debe negarse a
arrancar y decir por qué, no dar falsa sensación de cobertura. El motor de plantilla queda
disponible **solo** pasándolo explícito con `motor=` (tests y el mock por CLI con
`--motor plantilla`).

**Camino a la Jetson (documentado, no implementado).** El Orin Nano corre JetPack/L4T (CUDA,
cuDNN, TensorRT), GPU con 8 GB compartidos.
- **Ruta recomendada:** exportar el modelo rec a ONNX (`paddle2onnx`) y correrlo con
  `onnxruntime-gpu` (proveedor TensorRT/CUDA), en vez de instalar `paddlepaddle` en el edge.
  Es más ligero y estándar en aarch64.
- **No verificable en el dev de Windows:** `paddle2onnx` falla al cargar su DLL en Windows
  (problema conocido de esa plataforma; funciona en Linux/aarch64). **La paridad ONNX↔modelo
  original queda pendiente de validar en el target Linux/Jetson** en la iteración de
  despliegue. No bloquea la elección del motor, que se decidió por calidad de lectura.
- **Fallbacks:** `paddlepaddle` directo en Jetson vía wheels aarch64; o EasyOCR (PyTorch para
  Jetson) si Paddle resultara demasiado frágil en el hardware real. La regla acordada:
  **la seguridad de lectura pesa más que la elegancia de despliegue**.
- **Offline (ADR-008/009):** PaddleOCR descarga el modelo la primera vez; hay que
  pre-descargarlo y empaquetarlo para un hospital sin internet. Para el edge conviene el
  modelo **mobile** (más ligero) en vez del `medium` por defecto del dev.

**Consecuencias.** (+) El frame real se lee correctamente y el test de aceptación pasa (ya no
es `xfail`); se salta si el motor no está instalado. (+) Todas las salvaguardas de las
iteraciones 1–2 siguen intactas: el motor se enchufa *detrás* de ellas. (+) La suite corre
verde con el motor (113 pasan) y verde con skips sin él (0 fallos). (−) La dependencia de
producción es pesada y descarga modelos; el despliegue offline y el camino ONNX en Jetson son
trabajo de la iteración de despliegue. (−) La decisión se tomó sobre **una** muestra (SimCore,
9 variantes); se reconfirmará con la muestra del **uMEC12 real** cuando llegue de la
capturadora.

---

## ADR-017 — Paddle Inference segfaultea en aarch64: producción pasa a RapidOCR/ONNX Runtime

**Estado:** Aceptada (ago 2026)

**Contexto.** Al desplegar el motor de ADR-016 en el target real (Jetson Orin Nano, JetPack 6 /
L4T r36, aarch64, env conda `ocr-monitoreo` con Python 3.10) apareció el riesgo que aquel ADR
dejó anotado: toda la cadena instala, `paddleocr` importa, el **core** de PaddlePaddle opera
(aritmética de tensores OK), pero **Paddle Inference crashea con SIGSEGV en la primera pasada
del modelo OCR, de forma reproducible**. Se descartaron como causa: límite de hilos
(`OMP/OPENBLAS_NUM_THREADS=1`), `FLAGS_use_mkldnn=0`, aislamiento de `~/.local`
(`PYTHONNOUSERSITE=1`) y numpy 1.26.4. Conclusión: el wheel de Paddle Inference para aarch64
es inestable en esta placa. Sin motor, el módulo no lee nada en producción.

**Decisión.** El motor de producción pasa a **RapidOCR sobre ONNX Runtime**
(`rapidocr-onnxruntime==1.4.4`, adaptador `ocr/motor/rapid.py`): ejecuta los **mismos modelos
PP-OCR (v4)** exportados a ONNX, en modo **reconocimiento** sobre nuestras ROIs (sin
detección), con `onnxruntime` (CPUExecutionProvider), que corre estable en aarch64. Par
validado en la Jetson: `rapidocr-onnxruntime==1.4.4` + `onnxruntime==1.22.1` (se pinnea solo
rapidocr; onnxruntime lo resuelve pip — en dev resolvió 1.23.2 con resultados idénticos).

**Evidencia.**
- **Banco (Jetson, frame real de la capturadora):** FC 73 (0.9998), SpO2 98, FR 14, Temp 36.8,
  PNI 120/75 (0.9993) y MAP 90, sin ningún segfault.
- **Sonda de API (1.4.4):** `engine(img, use_det=False, use_cls=False, use_rec=True)` →
  `([[texto, score]], [tiempos])`, una entrada por ROI; imagen negra → `[['', 0.0]]`; el
  separador `/` de la PNI se preserva (`'120/75'`); acepta gris y vistas no contiguas.
- **Paridad medida en dev (evaluar_motores.py):** RapidOCR y PaddleOCR leen **idéntico**
  (6/6 en frame limpio, 9/9 en frames perturbados, 0 valores falsos ambos), y RapidOCR es
  **~21× más rápido en CPU** (88 ms vs 1909 ms por frame).
- **Modelos empaquetados:** el wheel trae los `.onnx` dentro (det 4.7 + rec 10.9 + cls
  0.6 MB): **no descarga nada en runtime** → apto para despliegue hospitalario sin internet,
  sin pre-sembrado de `~/.paddlex`.

**Lo que NO cambia.** La interfaz `LectorOCR`, la entrada cruda al motor, el saneo mínimo
(espacios fuera, letras dentro para que el lector las rechace), todas las salvaguardas del
lector, el contrato 1.1, el publicador y el fail-hard de `motor_por_defecto()` (ahora apunta a
rapidocr). El swap es exactamente el que ADR-013 prometía: una clase nueva.

**Consecuencias.** (+) Motor estable en el target de producción y mucho más ligero (arranque
en ~s y 88 ms/frame en CPU; la dependencia pesa MB, no GB). (+) Offline resuelto de fábrica.
(+) `LectorPaddleOCR` se conserva como adaptador alternativo en x86_64 (evidencia ejecutable
de ADR-016), pero **fuera de `requirements-motor.txt`** y del CLI. (−) CPU-only por ahora: el
ExecutionProvider de GPU/TensorRT queda como optimización futura si el ritmo lo pidiera (a
1 Hz rec-only sobra; **seguimiento**: medir ms/frame en la Orin en el banco). (−) API de
RapidOCR fijada por sonda contra la 1.4.4 pinneada; subir de versión exige re-sondear.

---

## ADR-018 — Capturadora por identidad estable (serial/by-id) con fail-hard, no por índice

**Estado:** Aceptada (ago 2026)

**Contexto — el incidente del banco (10 ago 2026).** En el despliegue en vivo se perdió un
buen rato con "todos los signos en null" por identidad de dispositivo, no por OCR: al
reconectar hardware, `/dev/video0` pasó a ser **una webcam** y el OCR leyó la webcam (todo
`null` — el sistema no inventó, pero el operador no sabía por qué); al quitar la webcam, la
capturadora reapareció en `/dev/video2`, con `/dev/video3` como nodo de metadatos. El índice
`/dev/videoN` **baila** con el orden de enumeración USB. En un sistema clínico, apuntar al
índice equivocado puede colgar una cama de **otra fuente** — con `cama_id` como pegamento del
sistema, es inaceptable.

**Realidad del target (sonda en la Jetson).**
- `/dev/v4l/by-id/usb-UltraSemi_USB3_Video_35562055-video-index0 → ../../video2` y
  `-video-index1 → ../../video3`: identidad estable **con serial único** (`35562055`).
- El nombre de tarjeta sysfs es **idéntico** en ambos nodos ("USB3 Video: USB3 Video"): el
  nombre NO distingue captura de metadatos → elegir nodo exige capacidades reales.
- `by-path` disponible (`platform-3610000.usb-usb-0:1.3:1.0`): identifica el puerto físico.

**Decisión** (`ocr/dispositivos.py` + `FuenteCapturadora`):
1. `--dispositivo` acepta, además de ruta/índice, una **identidad estable**: subcadena
   (insensible a mayúsculas) del nombre `by-id`, del `by-path` o del nombre de tarjeta —
   p. ej. el serial `35562055` o el modelo `UltraSemi`.
2. El **nodo** se elige por capacidades reales (`VIDIOC_QUERYCAP`, `device_caps` con
   `V4L2_CAP_VIDEO_CAPTURE`), no por la convención `-video-index0`: confirmado en el target
   que el nombre no distingue, así que la capacidad es el único criterio válido. La
   validación de modo (MJPG 1920×1080) sigue donde estaba: el primer frame real.
3. **Fail-hard sin fallback**: identidad ausente → `RuntimeError` accionable (qué se buscó,
   qué hay, cómo listarlo). **Prohibido caer a `/dev/video0`** — eso fue exactamente leer la
   webcam. Ambigüedad (≥2 coincidencias) → error pidiendo desambiguar por serial o `by-path`.
4. **Literales = el usuario manda**: rutas (`/dev/...`) e índices (dígitos de ≤3 caracteres,
   `0..999` — ningún `/dev/videoN` real pasa de ahí) se abren tal cual, sin resolución. Un
   dígito-largo (el serial `35562055`) es identidad: interpretarlo como índice abriría "la
   cámara nº 35562055", un sinsentido silencioso.
5. **La resolución ocurre una sola vez, al arrancar.** Si el dispositivo se desenumera a
   mitad de corrida, `frame()` lanza (iteración 5) y el proceso termina; el rearranque
   re-resuelve en frío. Re-resolver en caliente sería **cambiar de fuente en silencio** —
   la clase de fallo que este ADR viene a eliminar.
6. Operativa: `--listar-dispositivos` (tabla con nombre, serial, by-id, by-path y qué nodo
   es captura vs metadatos) y `ocr/herramientas/sondear_dispositivos.py` como herramienta de
   campo — el primer paso del diagnóstico "todos null": ¿de verdad lees la capturadora?

**Endurecimiento tras la revisión adversarial.** La revisión encontró (y se cerró con tests)
que la protección de ambigüedad solo actuaba con ambos dispositivos presentes: con la
capturadora **ausente** y una webcam genérica conectada, un identificador vago (`usb`,
`usb3`, `camera`) habría coincidido solo con la webcam y la habría abierto **en silencio** —
la clase exacta del incidente, sin síntoma en el arranque. Por eso:
1. **Guardia de especificidad**: identificadores de <5 caracteres o de una lista de términos
   genéricos (`usb`, `video`, `camera`, `hdmi`, `platform`…) se **rechazan en el arranque**
   con un error que recomienda el serial. Los apodos cortos se rechazan a propósito.
2. **Match campo por campo** (by-id, by-path, nombre), nunca sobre campos concatenados: un
   haystack unido permitía matches que cruzan campos con semántica impredecible.
3. **Varios nodos de captura en un dispositivo** (capturadora dual-HDMI) → error pidiendo la
   ruta explícita, no elección silenciosa; y los nodos se ordenan **numéricamente**
   (`video10` después de `video2` — el orden lexicográfico los invertía).
4. El parámetro se **normaliza (strip) antes de clasificar**: `" 0"` de un unit file es el
   índice 0, no una identidad cuya aguja `"0"` coincidiría con casi cualquier by-path.

**Alternativa considerada y descartada.** Una regla udev por Jetson
(`SYMLINK+="capturadora-cama09"`) es más "unix", pero mueve configuración clínica fuera del
repo, a cada placa, inauditable desde git. Queda como endurecimiento operativo futuro, no
como sustituto de la resolución en código.

**Consecuencias.** (+) El identificador recomendado del runbook es el serial (`35562055`);
reconectar hardware o añadir webcams ya no puede desviar la lectura a otra fuente sin que el
sistema lo grite. (+) Multi-cama futura: dos capturadoras idénticas se desambiguan por
`by-path` (puerto físico) — y con el matiz conocido de que dos unidades **sin serial único
colisionarían en `by-id`** (udev deja un solo symlink), `by-path` es el camino desde ya.
(+) Solo stdlib (`sysfs` + `ioctl`), sin binarios del sistema ni pip nuevos. (−) La
resolución por identidad requiere Linux/V4L2 (en dev, error claro y tests con enumeración
mockeada). (−) El default de `--dispositivo` sigue siendo `/dev/video0` por
retrocompatibilidad: la práctica recomendada (runbook) es fijar el serial.

---

## ADR-019 — Dashboard: video a demanda + política de conexión WebRTC

**Estado:** Aceptada (ago 2026)

**Contexto — el síntoma del banco (12 ago 2026).** Con un stream publicado a `cama-09`, la
tarjeta del dashboard se quedaba en "Reconectando…" en negro, mientras el reproductor directo
de MediaMTX reproducía el mismo stream desde el mismo navegador. Además, la rejilla abría un
PeerConnection por cama SIEMPRE — insostenible para la meta (~10 cámaras × ~5 espectadores,
remotos por Tailscale).

**Diagnóstico (con evidencia reproducida, no supuesta).** El diagnóstico se hizo por capas
sobre el servidor real desde dev, en este orden:
1. **CORS descartado con sonda HTTP**: OPTIONS y POST al endpoint WHEP real devuelven
   `Access-Control-Allow-Origin: *` (MediaMTX lo trae de fábrica).
2. **Síntoma reproducido** con el cliente real servido en `:8080` contra el MediaMTX real:
   `connecting → failed` en bucle, sin ningún error de fetch — la señalización funciona.
3. **Causa raíz**: el SDP answer de MediaMTX anuncia **un único candidato ICE:
   `127.0.0.1:8189` (loopback)** — inalcanzable desde cualquier otra máquina; todos los
   pares ICE fallan.
4. **Prueba positiva**: reescribiendo en el cliente `127.0.0.1` → `100.110.157.112` en el
   answer, la misma conexión pasa a `connected` con par ICE nominado y pista de video
   recibida. El único problema es la dirección anunciada; UDP 8189 fluye por la tailnet.
   (El reproductor directo funciona de chiripa: chequeos servidor→cliente con resolución
   mDNS en la misma LAN generan pares peer-reflexive — frágil y no generalizable.)

**Decisión.**
1. **Arreglo raíz (servidor, lo aplica Dr. Milton):** `webrtcAdditionalHosts:
   [100.110.157.112, 192.168.110.4]` en `mediamtx.yml` + restart. Documentado en el runbook
   como configuración obligatoria. Pendiente de su `grep -i webrtc` para entender por qué la
   enumeración de interfaces solo dio loopback (posible sandbox del servicio systemd).
2. **Cliente endurecido** (`lib/whep.ts`), correcto cross-red:
   - **Sin servidores ICE por defecto** (fuera el STUN de Google hardcodeado): entre pares de
     la tailnet los candidatos host bastan y el hospital no tiene internet (ADR-008/009).
     `NEXT_PUBLIC_ICE_SERVERS` (JSON) para escenarios futuros.
   - **Gracia para `disconnected`** (~4 s): suele ser transitorio y recuperarse; derribar al
     primer `disconnected` fabricaba bucles de reconexión. Solo `failed` derriba de inmediato.
   - **Etiquetas que diagnostican**: `404` → "Sin cámara (nadie publica)"; fallo de red/CORS
     → "Sin conexión con el servidor de video"; ICE caído → "Reconectando…".
   - **Detector del fallo de hoy**: si el answer solo trae candidatos loopback, la consola
     lo advierte con el arreglo exacto (`webrtcAdditionalHosts`). El incidente queda
     codificado como diagnóstico permanente.
   - **"Conectado" se declara solo en `connectionState === 'connected'`** (hallazgo de la
     revisión adversarial): por spec WebRTC el evento `track` se dispara al aplicar el SDP
     answer, ANTES de que ICE conecte — declarar conectado ahí mostraba un panel negro
     falso-conectado precisamente en el incidente loopback, tapando las etiquetas. La rama
     `connected` además re-engancha una recuperación tardía tras derribo por gracia y
     cancela el retry pendiente (que habría destruido una conexión viva).
   - **Solo video**: las cámaras no llevan micrófono (ADR-010); reintroducir el transceiver
     de audio es una línea documentada.
3. **Video A DEMANDA**: la rejilla **no abre conexiones WebRTC** — muestra datos + placeholder
   ("Video en el detalle"); el video vivo se conecta únicamente al abrir el detalle de una
   cama y se cierra al cerrarlo. El triaje en rejilla es por datos (que es el diseño clínico).
   Escala: espectador × cama enfocada = 1 PC, no espectador × todas.
4. **Página de diagnóstico `/diag.html?stream=<nombre>`**: monta el cliente WHEP real contra
   cualquier stream sin depender de MQTT — la herramienta del operador cuando un video no
   conecta.

**Verificación (E2E local, dev):** con MediaMTX + ffmpeg locales y el build servido en
`:8080`: conexión `connecting → connected` y video reproduciendo (640×480); 404 → etiqueta
correcta; rejilla con 5 camas reales descubiertas por MQTT y **cero** elementos de video;
abrir detalle → 1 video reproduciendo; cerrarlo → 0. Contra el servidor real (aún sin el
arreglo): la advertencia de loopback dispara con el mensaje accionable. `npm run build`
limpio (y sin `.babelrc`: se eliminó tras verificar que el build con SWC pasa).

**Seguimiento separado (no en este ADR):** espectadores remotos **fuera** de la tailnet
(TURN, exposición de puertos). Hoy remoto = vía Tailscale, que además es lo único compatible
con CONTEXT §2 ("nada de exponer puertos a internet abierto"). Si algún día se quiere
internet abierto, será su propia decisión con sus propias implicaciones de seguridad.

---

## ADR-020 — Video por cama: runner supervisado con identidad estable

**Estado:** Aceptada (ago 2026)

**Contexto.** El video de una cama se transmitía con un `ffmpeg` escrito a mano: moría con
`Broken pipe` cuando MediaMTX reiniciaba (relanzarlo era manual), apuntaba a `/dev/videoN`
(que baila con el USB — la clase de incidente de ADR-018) y no tenía estructura por
`cama_id`. La meta (~10 cámaras encendidas todo el día) exige que el stream sobreviva
reinicios y glitches **sin intervención**.

**Decisión: `python -m video.transmitir`** — runner independiente por cama (como
`ocr.publicar` lo es del dato; sin lanzador combinado, decisión explícita), paquete
top-level `video/` sin ninguna dependencia pip (reusa `ocr.dispositivos` **solo por
importación**; `ffmpeg` es el único binario externo).

1. **Encode x264 software, sin NVENC.** El Orin Nano **no tiene codificador por hardware**
   (el bloque NVENC se eliminó en Nano; sí conserva decodificador — el matiz importa al
   leer specs de la familia Orin). `-preset ultrafast -tune zerolatency -g <fps>` (1
   keyframe/s), CBR con la proporción validada en banco (`2M/2M/1M`; el perfil bajo
   640×480/800k la conserva), `-input_format mjpeg` (YUYV crudo corrompe buffers por USB),
   RTSP por TCP. El argv exacto está fijado por test (`test_comando.py`): el comando ES el
   artefacto validado.

2. **Supervisión de la TRANSMISIÓN, no solo del proceso.** `proc.wait()` solo ve salidas,
   y hay dos cuelgues reales donde ffmpeg NO sale: el demuxer v4l2 bloqueado en una cámara
   UVC atascada, y el `send()` TCP bloqueado en una caída silenciosa del camino (half-open:
   el kernel tarda ~15 min en rendirse). En ambos, el dashboard mostraría un **frame
   congelado que parece video en vivo** — el equivalente en video de servir un dato viejo
   como actual (el pecado clínico de este proyecto). Por eso ffmpeg corre con
   `-progress pipe:1` y un hilo lector renueva una marca de progreso; sin progreso en
   ~10 s (configurable, ≥ 2 s y finito: `nan`/`inf` desactivarían el watchdog en silencio)
   → terminate → gracia 3 s → kill → mismo ciclo de reintento. El wait post-kill está
   **acotado** (10 s): un ffmpeg en estado D (driver v4l2/xhci colgado) no muere ni con
   SIGKILL, y esperarlo sin tope colgaría al supervisor dentro de su propio camino de
   kill — ese caso es fatal ruidoso (relanzar abriría otro ffmpeg contra un nodo
   secuestrado; el remedio es reconectar la cámara o reiniciar, con `dmesg` como pista).
   Prueba de banco del estancamiento: NO es "tapar la cámara" (una lente cubierta sigue
   entregando frames negros y el progreso avanza) — es cortar en silencio el camino TCP a
   MediaMTX a media transmisión (`sudo iptables -A OUTPUT -p tcp --dport 8554 -j DROP`,
   verificar el derribo+relanzamiento, y retirar la regla con `-D`).

3. **Backoff con reset por corrida sana.** 1, 2, 4, 8, 16, 30 s (tope); una corrida ≥ 30 s
   resetea el contador. Un restart de MediaMTX a medianoche relanza en 1 s; una cámara
   ausente no gira en bucle caliente. La salida con código 0 también relanza (stream caído
   es stream caído). Reintento **indefinido** para cámara/red (decisión explícita): la
   ausencia de video es visible como verdad en el dashboard (MediaMTX tira el stream), así
   que perseverar no puede presentar datos falsos; el log repite el motivo en cada intento.
   Señalización activa de "cama sin video" (p. ej. estado por MQTT) = seguimiento separado.

4. **Matriz arranque estricto / corrida persistente.** En el arranque hay un humano
   delante: identidad ausente/ambigua, identidad **física no fijable** (el nodo no aparece
   en la enumeración V4L2 — sin pin, los relanzamientos no podrían verificar la fuente),
   `ffmpeg` fuera del PATH o flags inválidos fallan fuerte con mensaje accionable
   (exit 1). A media corrida no lo hay: cámara o red caídas reintentan para siempre.
   **Entorno roto es fatal siempre** (ffmpeg desaparecido: reintentar no lo arregla;
   ffmpeg inmatable en estado D: ídem). El primer intento de *transmisión* fallido
   (MediaMTX aún arrancando tras un power-cycle del rack) NO es fatal: entra al backoff —
   el rack completo debe auto-sanar. El reset del backoff mide la transmisión **sana**
   (hasta el último progreso real), no la duración total: una cámara que se congela cada
   ~25 s no debe girar en caliente porque la detección+matanza inflen la cuenta.

5. **Identidad con pin físico (extiende ADR-018 al relanzamiento automático).** La
   clasificación identidad/ruta/índice replica las reglas de `FuenteCapturadora`
   (réplica deliberada: cero ediciones en `ocr/`). ADR-018 prohíbe re-resolver *en
   caliente*; aquí cada relanzamiento es un arranque nuevo, pero re-resolver una aguja
   ambigua (nombre, o el by-id de una webcam sin serial) podría cambiar de fuente en
   silencio. Por eso en la **primera** resolución se fija (pin) la identidad física
   completa del dispositivo y cada relanzamiento debe resolver **al mismo**:
   - **Cámara con serial único** (capturadora UltraSemi `35562055`) → pin por `by-id`: el
     serial identifica la unidad; puede cambiar de puerto USB y se la sigue.
   - **Webcam sin serial** → pin por `by-path`: el **puerto físico** es la única ancla.
     Evidencia de la sonda del banco (21-ago-2026): la webcam Jieli reporta
     `by-id usb-Jieli_Technology_USB_Composite_Device` — sin serial; el token final
     "Device" es placeholder. La heurística de "serial utilizable" exige: trae dígitos,
     NO está en la lista de placeholders de fábrica conocidos (`0001`, `01.00.00`,
     `20200101`… — iSerial idéntico en todas las unidades del modelo, común en UVC
     baratas), y ningún otro dispositivo enumerado comparte el by-id. Dos webcams
     idénticas comparten by-id: intercambiarlas solo lo detecta el puerto. Requiere
     **etiquetado físico de puertos** y la tabla puerto↔cama del runbook.
   - Identidad que resuelve a OTRO dispositivo físico → **no se lanza**; se espera a la
     original con backoff (puede volver; el log dice cómo aceptar un cambio intencional:
     reiniciar el runner re-fija el pin). Enumeración que no confirma el nodo en un
     relanzamiento → tampoco se lanza (esperar es reintetable; transmitir sin verificar
     sería el fallback silencioso que este proyecto prohíbe). Nodo **literal** que ahora
     es otra cámara → **fatal ruidoso**: relanzar transmitiría la cama equivocada. La
     verificación compara el **atributo fijado** (no recalcula la política: si un clon
     aparece después de fijar el pin, la original debe seguir coincidiendo).
   - La heurística es conservadora a propósito: ante la duda se ancla al puerto (más
     estricto, nunca menos seguro). **Residual documentado**: un placeholder con dígitos
     fuera de la lista, con UNA sola unidad enchufada al fijar el pin, no es detectable —
     un clon enchufado después en otro puerto pasaría el pin by-id. Por eso el runbook
     manda elegir las webcams sin serial por **by-path** (la propia aguja ancla el
     puerto y un clon en otro puerto ni siquiera coincide con ella).

6. **Supervisión en Python, no systemd ni GStreamer.** systemd con `ExecStart` estático no
   puede re-resolver identidad ni verificar el pin en cada relanzamiento (relanzaría el
   ffmpeg apuntando al nodo viejo = el incidente de ADR-018); GStreamer añadiría una
   dependencia (gst-python en el env aislado de la Jetson) y abandonaría el comando ffmpeg
   exacto que el banco validó. systemd **compone por encima** como capa futura
   (`Restart=always` del runner para sobrevivir reboots/OOM): el CLI ya mapea SIGTERM al
   mismo cierre limpio que Ctrl+C, y el ffmpeg se lanza con `PR_SET_PDEATHSIG` (muere con
   el runner: sin huérfanos reteniendo `/dev/videoN` con EBUSY). Cierre limpio sin handler
   de SIGINT: `KeyboardInterrupt` emerge de `wait()`/`sleep` (PEP 475) y el apagado
   (terminate → gracia → kill) corre en `except`/`finally` — el patrón de
   `ocr.publicar.correr`, fijado por tests que corren en Windows.

7. **Riesgo residual nombrado: cámara equivocada por misconfig humana.** El `cama_id` es
   el pegamento datos↔video y solo el operador lo teclea. Mitigaciones de esta iteración:
   flag obligatorio sin default, formato `cama-NN` validado, y log de mapeo inequívoco
   (`[cama-09] <- by-path …usb-0:2.2… (/dev/video2) -> rtsp://…/cama-09`) en **cada**
   (re)lanzamiento. Dos runners publicando al mismo path se manifiestan como video que
   "parpadea" entre cámaras (síntoma documentado en el runbook). La mitigación de fondo
   (config declarativa por edge + verificación visual al dar de alta una cama) queda como
   seguimiento; la **auth de publicación/lectura en MediaMTX** entra a la lista de
   endurecimiento pre-hospitalario de CONTEXT §2.

**Aceptación** (banco, Dr. Milton): transmitir eligiendo por by-path sin importar el
`/dev/videoN`; `sudo systemctl restart mediamtx` a media transmisión → reconecta solo;
estancar la transmisión sin matarla (la regla `iptables … --dport 8554 -j DROP` del punto
2) → el watchdog derriba y relanza; 720p/2M y 640×480/800k; cámara inexistente → fallo
accionable. En dev: `pytest` (suite canónica con `pytest.ini`: `ocr/tests` +
`video/tests`) y `compileall` limpios.
