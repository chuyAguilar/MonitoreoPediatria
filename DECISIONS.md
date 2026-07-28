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
| ADR-016 | Motor OCR de producción: PaddleOCR, con entrada cruda al motor | Aceptada |

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

**Estado:** Aceptada (jul 2026)

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
