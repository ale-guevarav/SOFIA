# SOFIA - Sistema de Detección de Posturas

Sistema de visión por computadora desarrollado para el robot **SOFIA**, enfocado en la detección de la estructura corporal, manos y posturas de una persona en tiempo real.

El objetivo del proyecto es permitir que SOFIA pueda interpretar gestos corporales para interactuar con una persona durante una dinámica basada en el juego **Vaqueritos**.

## Primera entrega

En esta primera etapa se implementó el sistema base de visión por computadora. El programa utiliza una cámara para detectar a una persona y representar en tiempo real los puntos clave de su cuerpo y manos.

Actualmente el sistema permite:

* Capturar video en tiempo real mediante una cámara.
* Detectar la estructura corporal de una persona.
* Obtener los 33 landmarks proporcionados por MediaPipe Pose Landmarker.
* Dibujar los puntos y conexiones del esqueleto corporal.
* Filtrar landmarks corporales con baja visibilidad.
* Detectar hasta dos manos simultáneamente.
* Obtener 21 landmarks por cada mano.
* Dibujar las articulaciones y conexiones de los dedos.
* Procesar Pose y Hands simultáneamente.
* Mostrar los FPS durante la ejecución.
* Indicar visualmente si existe una persona detectada.
* Registrar métricas de desempeño (tasa de acierto, tiempo de respuesta y FPS promedio) y generar reportes en Excel y Markdown.
* Reconocer automáticamente las cinco posturas del juego.
* Seguir la posición de la mano en un plano cartesiano (modo TRACKING).
* Operar el sistema desde una **interfaz gráfica (GUI)** con video en vivo y botones para iniciar, pausar, reanudar y detener la detección.
* Enviar las posturas y la posición de la mano al **ESP32 maestro por Bluetooth Low Energy (BLE)**.

El sistema puede trabajar con hasta **75 landmarks simultáneamente**:

```text
33 landmarks del cuerpo
+ 21 landmarks de la mano izquierda
+ 21 landmarks de la mano derecha
= 75 landmarks
```

---

## Tecnologías utilizadas

### Python 3.12

Se eligió Python debido a su facilidad de desarrollo y a la gran cantidad de librerías disponibles para visión por computadora y procesamiento de datos.

También permite realizar prototipos rápidamente y cuenta con compatibilidad con las herramientas utilizadas en el proyecto.

### Visual Studio Code

Se utiliza Visual Studio Code como entorno de desarrollo debido a que es ligero, permite trabajar fácilmente con entornos virtuales de Python y cuenta con herramientas de depuración, terminal integrada y soporte para Git.

### OpenCV

OpenCV se utiliza principalmente para:

* Acceder a la cámara.
* Capturar los frames de video.
* Convertir formatos de imagen.
* Dibujar líneas, puntos y texto sobre la imagen.
* Mostrar el resultado del procesamiento en tiempo real.

### MediaPipe

MediaPipe proporciona los modelos de visión utilizados para obtener los landmarks del cuerpo y las manos sin necesidad de entrenar un modelo propio.

Se utilizan dos componentes:

**Pose Landmarker**

* Detecta la estructura corporal.
* Proporciona 33 landmarks.
* Permite conocer la posición de hombros, brazos, codos, muñecas, torso, piernas y otros puntos del cuerpo.

**Hand Landmarker**

* Detecta hasta dos manos.
* Proporciona 21 landmarks por mano.
* Permite obtener información de las articulaciones de los dedos.

El uso de Hand Landmarker será especialmente útil para reconocer gestos donde la posición de los dedos sea importante.

### NumPy

NumPy forma parte de las herramientas utilizadas para el procesamiento numérico y será utilizado para operaciones geométricas relacionadas con los landmarks, como cálculo de distancias, vectores y ángulos entre articulaciones.

### Matplotlib y openpyxl

Se utilizan para generar los reportes de métricas:

* **Matplotlib** crea las gráficas en imagen (pastel, barras, líneas y matriz de confusión) para el reporte en Markdown.
* **openpyxl** crea el archivo de Excel con tablas y gráficas nativas que se pueden editar.

### PySide6 (Qt)

Se utiliza para la interfaz gráfica. Se eligió porque incluye lo necesario para que el procesamiento de video no congele la ventana:

* `QThread` para correr la cámara y MediaPipe en un hilo aparte.
* Señales y slots para pasar datos entre hilos de forma segura.
* `QMutex` y `QWaitCondition` para pausar el hilo sin consumir CPU.

> Se usa la versión **6.11.2**. La 6.12.0 tiene un error que cierra el programa.

### Bleak

Librería para **Bluetooth Low Energy** desde Python. Se usa porque el ESP32-C3 solo tiene BLE (no tiene Bluetooth clásico), así que no aparece como puerto COM.

---

## ¿Por qué se eligieron estas tecnologías?

La combinación de **Python + OpenCV + MediaPipe** permite desarrollar un sistema de visión por computadora en tiempo real sin necesidad de crear y entrenar desde cero una red neuronal para reconocimiento corporal.

Las principales ventajas para este proyecto son:

* Facilidad de implementación.
* Modelos previamente entrenados.
* Procesamiento en tiempo real.
* Detección corporal y de manos.
* Compatibilidad con cámaras convencionales.
* Gran cantidad de documentación y soporte.
* Posibilidad de calcular posturas mediante geometría a partir de los landmarks.
* Facilidad para integrar posteriormente el sistema con la lógica de SOFIA.

---

## Estructura del proyecto

```text
SOFIA/
├── Vision/                       ← este proyecto
│   │
│   │   # Programas que se ejecutan
│   ├── main.py                   ← ventana de OpenCV con teclado (y métricas)
│   ├── gui_app.py                ← interfaz gráfica
│   ├── ble_test.py               ← prueba de comunicación con el ESP32
│   │
│   ├── deteccion/                ← cámara → postura / posición de la mano
│   │   ├── vision_pipeline.py
│   │   ├── gesture_recognition.py
│   │   ├── gesture_detector.py
│   │   ├── hand_tracker.py
│   │   ├── pose_detector.py
│   │   ├── hand_detector.py
│   │   ├── pose_connections.py
│   │   ├── hand_connections.py
│   │   ├── geometry_utils.py
│   │   └── smoothing.py
│   │
│   ├── interfaz/                 ← piezas de la GUI
│   │   ├── vision_worker.py
│   │   └── sim_camera.py         ← imágenes de la cámara de Webots
│   │
│   ├── comunicacion/             ← Bluetooth con el ESP32 / Webots
│   │   ├── protocol.py
│   │   ├── ble_link.py
│   │   └── sim_link.py           ← mismo protocolo por TCP (Webots)
│   │
│   ├── evaluacion/               ← métricas del modo TEST
│   │   ├── metrics_logger.py
│   │   └── generate_report.py
│   │
│   ├── docs/                     ← explicación del código
│   │   ├── ARQUITECTURA_GUI.md
│   │   └── PROTOCOLO_COMUNICACION.md
│   │
│   ├── models/
│   │   ├── pose_landmarker.task
│   │   └── hand_landmarker.task
│   │
│   ├── metrics/                  (se crea automáticamente; no se sube a git)
│   ├── requirements.txt
│   ├── .gitignore
│   └── README.md
│
├── ESP32/                        ← firmware del ESP32 maestro (ver ESP32/README.md)
└── Paper-Latex/                  ← documentos formales
```

Cada carpeta agrupa una parte del sistema, y en la raíz de `Vision/` solo quedan los tres programas que se ejecutan. Cada carpeta tiene un `__init__.py` que describe lo que contiene.

### `main.py`

Programa con ventana de OpenCV controlado con el teclado.

Se encarga de:

* Inicializar la cámara.
* Cambiar entre los modos JUEGO, TEST y TRACKING.
* Mostrar el resultado y los FPS.
* Registrar las métricas de desempeño (solo en modo TEST).
* Liberar los recursos al finalizar.

La detección en sí está en `vision_pipeline.py`, que es el mismo código que usa la GUI.

### `gui_app.py`

Interfaz gráfica. Muestra el video, el resultado, los botones de control, el selector de modo, la conexión con el ESP32 y una bitácora. **No procesa video**: eso lo hace `vision_worker.py` en otro hilo.

### `interfaz/vision_worker.py`

Hilo (`QThread`) que lee la cámara y ejecuta el pipeline. Implementa pausar, reanudar y detener, y manda cada frame y su resultado a la GUI mediante señales.

### `deteccion/vision_pipeline.py`

Procesa **un frame** según el modo activo:

* **JUEGO / TEST:** Pose + Manos + reconocimiento de posturas.
* **TRACKING:** solo Manos; Pose se usa únicamente como respaldo si la mano se pierde.

### `deteccion/gesture_recognition.py`

Decide qué postura se está haciendo a partir de los landmarks, usando las reglas de `gesture_detector.py` y la confirmación temporal de 5 frames.

### `deteccion/hand_tracker.py`

Calcula la posición de la mano en un plano cartesiano con el origen en el centro de la imagen y el vector desde el origen hasta la mano.

### `comunicacion/protocol.py`

Arma y valida las tramas del protocolo de comunicación con el ESP32 (ver `docs/PROTOCOLO_COMUNICACION.md`).

### `comunicacion/ble_link.py`

Conexión Bluetooth con el ESP32: busca el dispositivo, envía las tramas, espera la confirmación (ACK) y reintenta si no llega. Corre en su propio hilo.

### `comunicacion/sim_link.py`

Enlace con la simulación de Webots. Hereda de `ble_link.py` y solo cambia el transporte (TCP local), así las reglas del protocolo son idénticas. Incluye un emulador de canal (retraso, pérdidas y bytes dañados) para parecerse al BLE.

### `interfaz/sim_camera.py`

Hilo que recibe las imágenes de la cámara cenital de Webots por un canal aparte y las muestra en la GUI.

### `ble_test.py`

Prueba de comunicación sin GUI: envía un PING, una postura, un TRACK y una trama dañada, y muestra si cada una tuvo la respuesta esperada.

### `deteccion/pose_detector.py`

Contiene la lógica relacionada con MediaPipe Pose Landmarker.

Se encarga de detectar y dibujar la estructura corporal.

### `deteccion/pose_connections.py`

Define las conexiones utilizadas para representar gráficamente el esqueleto corporal.

### `deteccion/hand_detector.py`

Contiene la lógica relacionada con MediaPipe Hand Landmarker.

Se encarga de detectar y dibujar las manos y sus articulaciones. Los umbrales de confianza se pueden configurar: el modo TRACKING usa umbrales más bajos para no perder la mano tan fácilmente.

### `deteccion/hand_connections.py`

Define las conexiones entre los 21 landmarks de cada mano.

### `deteccion/gesture_detector.py`

Contiene las reglas geométricas para reconocer los cinco gestos a partir de los landmarks.

### `deteccion/geometry_utils.py`

Funciones de apoyo para calcular distancias, ángulos y distancias normalizadas.

### `deteccion/smoothing.py`

Suavizado de landmarks (EMA) y confirmación temporal para evitar detecciones inestables.

### `evaluacion/metrics_logger.py`

Mide el desempeño del sistema mientras se ejecuta: FPS, latencia por frame y resultados de las pruebas. Guarda todo en un archivo JSON.

### `evaluacion/generate_report.py`

Lee el JSON de métricas y genera el reporte en Excel (`.xlsx`) y Markdown (`.md`) con tablas y gráficas.

### `models/`

Contiene los modelos utilizados por MediaPipe:

```text
pose_landmarker.task
hand_landmarker.task
```

---

# Posturas y gestos

Para la interacción con SOFIA se diseñaron cinco gestos inspirados en la dinámica del juego **Vaqueritos**.

Los cinco se reconocen automáticamente mediante reglas geométricas sobre los landmarks de Pose Landmarker y Hand Landmarker. Cada postura tiene un número que se usa en las pruebas (teclas 1-5) y en la comunicación con el ESP32:

| # | Postura | Tipo | Condiciones principales |
| --- | --- | --- | --- |
| 1 | INICIO | Dinámica | Tres contactos muñeca-cadera en menos de 3 s |
| 2 | RECARGAR | Estática | Muñecas cerca de los hombros, antebrazos casi verticales, sin dos manos en pistola |
| 3 | ESCUDO | Estática | Brazos cruzados, muñecas cerca del hombro contrario, codos debajo de los hombros |
| 4 | ATAQUE | Estática | Ángulo de codos entre 35° y 125°, muñecas arriba de los codos y dos manos en pistola |
| 5 | FIN | Dinámica | Una mano levantada con dos cambios de dirección horizontales |

Las posturas estáticas deben mantenerse 5 frames seguidos para confirmarse.

## 1. INICIO - Tres palmadas

**Tipo:** Gesto dinámico.

La persona coloca las manos cerca de los muslos y realiza tres palmadas consecutivas sobre ellos.

**Función:**

Indicar el inicio de la partida o una transición hacia el modo de juego.

**Detección (diseño original; ver la tabla de condiciones actuales arriba):**

Se analizará la distancia entre las muñecas/manos y la zona de los muslos a través de varios frames, utilizando un contador para reconocer tres movimientos consecutivos.

---

## 2. RECARGAR

**Tipo:** Postura estática.

La persona flexiona ambos brazos y coloca las manos aproximadamente a la altura de los hombros, con los antebrazos casi verticales.

**Función:**

Recargar munición dentro del juego.

**Detección (diseño original; ver la tabla de condiciones actuales arriba):**

Se utilizarán las posiciones de:

* Hombros.
* Codos.
* Muñecas.

A partir de estos landmarks será posible calcular ángulos y distancias para determinar si ambos brazos se encuentran en la posición esperada.

---

## 3. ESCUDO

**Tipo:** Postura estática.

La persona cruza los brazos frente al pecho.

**Función:**

Protegerse de un ataque.

**Detección (diseño original; ver la tabla de condiciones actuales arriba):**

Se analizará la posición relativa de:

* Hombros.
* Codos.
* Muñecas.
* Torso.

Las muñecas deberán encontrarse cruzadas o posicionadas hacia lados opuestos del torso.

---

## 4. ATAQUE

**Tipo:** Postura principalmente estática.

La persona flexiona los brazos en forma de "W" (muñecas por encima de los codos) y realiza con ambas manos un gesto similar a una pistola.

**Función:**

Realizar un ataque contra SOFIA.

**Detección (diseño original; ver la tabla de condiciones actuales arriba):**

Pose Landmarker permitirá analizar la extensión y dirección de los brazos.

Hand Landmarker permitirá analizar individualmente los dedos para identificar una configuración similar a:

* Índice extendido.
* Pulgar extendido.
* Dedos medio, anular y meñique flexionados.

---

## 5. FIN / DESPEDIDA

**Tipo:** Gesto dinámico.

La persona levanta una mano y realiza un movimiento lateral de despedida.

**Función:**

Finalizar la interacción o indicar el término de la partida.

**Detección (diseño original; ver la tabla de condiciones actuales arriba):**

Se analizará la posición de las manos durante varios frames para detectar cambios repetidos de dirección de izquierda a derecha.

---

# Flujo actual del sistema

```text
Cámara
   │
   ▼
Hilo de visión (vision_worker.py)
   │
   ▼
VisionPipeline ── modo JUEGO ───► Pose + Hands ► posturas
   │                                              (INICIO, RECARGAR, ESCUDO, ATAQUE, FIN)
   └──────────── modo TRACKING ─► Hands ► posición de la mano (x, y, vector)
   │
   ▼
GUI (gui_app.py): video + resultado + controles
   │
   ▼
Hilo BLE (ble_link.py) ── trama + CRC ──► ESP32 maestro ──► PCA9685 ──► 2 servos
                       ◄── ACK / NACK ───
```

---

# Flujo futuro

```text
Posturas / posición de la mano
   │
   ▼
Lógica del juego
   │
   ▼
ESP32 maestro ──► 16 módulos de SOFIA
```

La lógica del juego podrá administrar aspectos como munición, acciones válidas, selección de acciones de SOFIA y condiciones de victoria o derrota.

---

# Instalación

## 1. Clonar el repositorio

```bash
git clone https://github.com/ale-guevarav/SOFIA
cd SOFIA
```

## 2. Crear un entorno virtual

```bash
python -m venv .venv
```

## 3. Activar el entorno virtual

En Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 4. Instalar dependencias

Desde la carpeta `SOFIA`:

```bash
pip install -r Vision/requirements.txt
```

Incluye OpenCV, MediaPipe, las librerías de reportes (Matplotlib, openpyxl), la GUI (PySide6) y Bluetooth (bleak).

---

# Ejecución

Con el entorno virtual activado, desde la carpeta `SOFIA` (o desde `Vision/`; los programas encuentran los modelos en cualquier caso):

| Programa | Para qué |
| --- | --- |
| `python Vision/gui_app.py` | **Interfaz gráfica**: uso normal y conexión con el ESP32 |
| `python Vision/main.py` | Ventana de OpenCV con teclado; aquí está el **modo TEST** con métricas |
| `python Vision/ble_test.py` | Probar la comunicación con el ESP32 sin GUI |

## Modos

| Modo | Qué hace |
| --- | --- |
| **JUEGO** | Reconoce las cinco posturas. |
| **TEST** | Igual que JUEGO, más pruebas y métricas (solo en `main.py`). |
| **TRACKING** | **No reconoce posturas.** Sigue la mano y la ubica en un plano cartesiano con el (0, 0) en el centro de la imagen. |

## Teclas en `main.py`

Haz clic en la ventana de la cámara antes de presionar:

| Tecla | Acción |
| --- | --- |
| `J` | Modo JUEGO |
| `T` | Modo TEST |
| `K` | Modo TRACKING |
| `M` | Siguiente modo |
| `Q` | Salir (y generar el reporte si se usó TEST) |

---

# Interfaz gráfica (GUI)

```bash
python Vision/gui_app.py
```

```text
┌──────────────────────────────────────┬──────────────────────────┐
│                                      │ Control de detección     │
│                                      │ [Iniciar]  [Pausar]      │
│                                      │ [Reanudar] [Detener]     │
│           VIDEO EN VIVO              │ Modo: (•) Juego ( ) Track│
│                                      │ Resultado: ESCUDO        │
│                                      │ ESP32: ● Conectado       │
│                                      │ Bitácora                 │
└──────────────────────────────────────┴──────────────────────────┘
```

| Botón | Qué hace |
| --- | --- |
| **Iniciar** | Crea el hilo de visión, abre la cámara y carga los modelos. |
| **Pausar** | El hilo se detiene sin consumir CPU (el video se congela). |
| **Reanudar** | El hilo continúa donde se quedó. |
| **Detener** | Termina el hilo, libera la cámara y manda STOP al ESP32. |

La ventana nunca se congela porque la cámara y MediaPipe corren en un hilo y el Bluetooth en otro. La arquitectura completa, los wireframes y la justificación están en `docs/ARQUITECTURA_GUI.md`.

---

# Modo TRACKING

El origen (0, 0) está en el centro de la imagen, con `+x` a la derecha y `+y` hacia arriba. Para cada mano se calcula:

* Coordenadas en píxeles y normalizadas de -1 a 1.
* Vector desde el origen: magnitud y ángulo (0° = derecha, sentido antihorario).

Para que la mano no se pierda cuando la palma se inclina, se usan tres niveles:

1. **Hand Landmarker** (lo más preciso).
2. Si la mano se pierde, la **muñeca de Pose Landmarker**, que no necesita ver la palma.
3. Si tampoco hay pose, se mantiene la **última posición** 0.35 s.

---

# Comunicación con el ESP32 (BLE)

La PC envía al ESP32 maestro las posturas y la posición de la mano por **Bluetooth Low Energy**. Cada mensaje es una trama con número de secuencia y CRC-8; el ESP32 responde **ACK** si la recibió bien o **NACK** con un código de error.

| Comando | Cuándo se envía |
| --- | --- |
| POSE (1-5) | Cuando aparece una postura nueva |
| TRACK (x, y, vector) | Continuamente en modo TRACKING (máx. 20 por segundo) |
| PING | Comando de prueba y latido cada segundo sin tráfico |
| MODE | Al conectar y al cambiar de modo |
| STOP | Al detener la detección |

**Para conectar desde la GUI:** encender el Bluetooth de la laptop, encender el ESP32 y presionar **Conectar**. No es necesario (ni recomendable) emparejarlo desde la configuración de Windows.

El estándar completo (trama, comandos, códigos de error y reglas) está en `docs/PROTOCOLO_COMUNICACION.md`. El firmware del ESP32 está en la carpeta `ESP32/` de la raíz del repositorio.

## Simulación en Webots

En el panel **Robot** de la GUI hay una conexión para el **ESP32 (Bluetooth)** y otra para **Webots (simulación)**, y los resultados se mandan a todas las que estén conectadas: solo Webots sirve para simular sin ESP32, y con las dos conectadas funciona como **gemelo digital** (mismos comandos al robot real y a la simulación). Con Webots se usan **las mismas tramas y reglas** (ACK, reintentos, latido, estado seguro), pero por un socket TCP local (`comunicacion/sim_link.py`). La cámara cenital de la simulación se ve junto al video con **Ver cámara de Webots**; llega por un canal aparte (`interfaz/sim_camera.py`). La opción **Simular canal BLE** agrega retraso y pérdidas para que se comporte como el Bluetooth real.

El mundo y los controladores están en la carpeta `Webots/` de la raíz del repositorio (ver `Webots/README.md`).

---

# Pruebas y métricas de desempeño

El modo **TEST** de `main.py` (tecla `T`) permite medir qué tan bien funciona el sistema. Las métricas solo se registran mientras se está en este modo. Las métricas registradas son:

* **Tasa de acierto:** porcentaje de pruebas en las que el sistema reconoció el gesto correcto.
* **Tiempo de respuesta:** cuánto tarda el sistema en reconocer un gesto.
* **FPS promedio:** qué tan fluido corre el sistema.

## Controles

Las teclas solo funcionan si la **ventana de la cámara está seleccionada** (haz clic en ella antes de presionar).

| Tecla | Acción |
| --- | --- |
| `1` | Probar **INICIO** |
| `2` | Probar **RECARGAR** |
| `3` | Probar **ESCUDO** |
| `4` | Probar **ATAQUE** |
| `5` | Probar **FIN** |
| `0` / `x` | **Modo libre:** cancela la prueba actual, no registra nada y no muestra nada en pantalla |
| `s` | Guardar las métricas sin cerrar el programa |
| `q` | Salir, guardar las métricas y generar el reporte |

## ¿Cómo funciona una prueba?

Cada prueba pasa por cuatro fases:

```text
Presionar 1-5
     │
     ▼
TESTING: <gesto>  3 → 2 → 1        (naranja)
Preparación. Lo que se detecte aquí NO cuenta.
     │
     ▼
TESTING: <gesto>  YA!              (rojo parpadeando)
La persona hace el gesto. Tiene 6 segundos.
Aquí empieza a medirse el tiempo de respuesta.
     │
     ▼
ACIERTO (verde)  /  FALLO (rojo)
Se muestra 1.5 segundos.
     │
     ▼
Modo libre (pantalla limpia)
```

Mientras no se inicie una prueba, el sistema sigue midiendo FPS y latencia en segundo plano, pero no calcula la tasa de acierto, porque no sabe qué gesto se esperaba.

## ¿Cómo se califica una prueba?

El **primer gesto** que detecte el sistema después del "YA!" decide el resultado:

| Resultado | Qué significa |
| --- | --- |
| ✅ **Acierto** | El sistema detectó el gesto que se estaba probando. |
| ❌ **No detectado** | Pasaron los 6 segundos y el sistema no detectó nada. |
| ❌ **Confundido** | El sistema detectó un gesto diferente al que se estaba probando. |

Un gesto se cuenta solo en el momento en que **aparece** (cuando cambia la postura mostrada en pantalla). Si la persona mantiene un gesto por varios segundos, se cuenta como una sola detección.

## Reglas para hacer pruebas válidas

1. **Empezar en posición neutral**, con los brazos abajo. Si el gesto ya está hecho antes del "YA!", el sistema no ve un cambio y la prueba puede salir como *No detectado*.
2. **Esperar el "YA!"** antes de hacer el gesto. Lo que ocurre durante la cuenta regresiva no se toma en cuenta.
3. **Hacer un solo gesto por prueba.** Si se hace otro gesto primero, la prueba cuenta como *Confundido*.
4. **No iniciar otra prueba** mientras aparezca "TESTING". Hay que esperar a que termine o cancelarla con `0`.
5. **Mantener a la persona completa en cámara**, al menos de la cadera hacia arriba y con buena iluminación.
6. **Dividir los roles:** lo ideal es que una persona presione las teclas y otra haga los gestos.

## Protocolo recomendado

Para que los resultados sean representativos:

* Realizar **al menos 10 pruebas por gesto** (50 en total).
* Alternar el orden de los gestos en lugar de hacer todos los de un mismo tipo seguidos.
* De ser posible, repetir con **distintas personas**, distancias a la cámara y condiciones de iluminación.
* Guardar cada sesión por separado para poder compararlas.

## ¿Cómo se miden las métricas?

### Tasa de acierto

```text
Tasa de acierto = aciertos / pruebas totales × 100
```

También se calcula por cada gesto, junto con:

* **Precisión:** de las veces que el sistema dijo *X*, cuántas eran realmente *X*.
* **Recall:** de las veces que la persona hizo *X*, cuántas detectó el sistema.
* **F1:** combinación de precisión y recall en un solo valor.
* **Matriz de confusión:** tabla que muestra qué gestos se confunden entre sí. La diagonal corresponde a los aciertos.

### Tiempo de respuesta

Se mide de dos maneras:

* **Tiempo de reconocimiento (segundos):** tiempo desde el "YA!" hasta que el sistema reporta el gesto. Solo se calcula en los aciertos. Incluye el tiempo que tarda la persona en moverse y los 5 frames de confirmación temporal, por lo que representa lo que percibiría un jugador frente a SOFIA.
* **Latencia por frame (milisegundos):** cuánto tarda el programa en procesar cada imagen. Se desglosa por etapa: Pose Landmarker, Hand Landmarker, lógica de gestos y dibujo. No incluye el tiempo de espera de la cámara.

### FPS promedio

```text
FPS promedio = frames procesados / tiempo total
```

Se reportan además el FPS mínimo, máximo y p95, una gráfica de FPS a lo largo de la sesión y la **capacidad de procesamiento** (los FPS que se alcanzarían si la cámara no limitara la velocidad).

## Resultados generados

Al presionar `q` (si se usó el modo TEST) se crean los siguientes archivos:

```text
metrics/
├── sesion_AAAAMMDD_HHMMSS.json        ← datos crudos de la sesión
└── reportes/
    └── sesion_AAAAMMDD_HHMMSS/
        ├── reporte.xlsx               ← tablas y gráficas en Excel
        ├── reporte.md                 ← reporte con tablas e imágenes
        └── graficas/                  ← gráficas en PNG
```

El **Excel** contiene cinco hojas: Resumen, Por gesto, Rendimiento, Matriz de confusión e Intentos.

El **Markdown** se puede ver en VS Code con clic derecho → *Open Preview*.

Si el reporte no se generó automáticamente, o se quiere regenerar:

```bash
cd Vision

# Sesión más reciente
python -m evaluacion.generate_report

# Sesión específica
python -m evaluacion.generate_report metrics/sesion_AAAAMMDD_HHMMSS.json
```

---

# Estado del proyecto

### Primera etapa

* [x] Captura de cámara.
* [x] Detección corporal.
* [x] 33 landmarks corporales.
* [x] Visualización del esqueleto.
* [x] Detección de manos.
* [x] 21 landmarks por mano.
* [x] Visualización de dedos.
* [x] Procesamiento en tiempo real.
* [x] Visualización de FPS.
* [x] Modularización de detectores.
* [x] Diseño de cinco posturas/gestos.

### Segunda etapa

* [x] Suavizado de landmarks corporales (EMA).
* [x] Confirmación temporal de posturas estáticas (5 frames consecutivos).
* [x] Reconocimiento automático de ESCUDO.
* [x] Reconocimiento automático de ATAQUE (brazos + dos manos en forma de pistola).
* [x] Reconocimiento de RECARGAR (primero dinámico, después redefinido como postura estática).
* [x] Reconocimiento dinámico de INICIO (tres palmadas).
* [x] Reconocimiento dinámico de FIN/DESPEDIDA.
* [x] Modo de pruebas con cuenta regresiva.
* [x] Registro de métricas de desempeño (tasa de acierto, tiempo de respuesta y FPS promedio).
* [x] Generación de reportes en Excel y Markdown con tablas y gráficas.

### Tercera etapa

* [x] Selector de modos (JUEGO / TEST / TRACKING).
* [x] Modo TRACKING con plano cartesiano y respaldo con Pose.
* [x] Interfaz gráfica con PySide6 y procesamiento en hilos.
* [x] Controles para iniciar, pausar, reanudar y detener la detección.
* [x] Estándar de comunicación PC-ESP32 por BLE (tramas, CRC, ACK/NACK y códigos de error).
* [x] Envío de posturas y posición de la mano desde la GUI.
* [x] Firmware del ESP32 con un patrón de movimiento por postura (carpeta `ESP32/`).
* [ ] Validación de la comunicación y del movimiento en el hardware real.

### Próximas etapas

* [ ] Máquina de estados para evitar detecciones repetidas.
* [ ] Implementación de la lógica del juego.
* [ ] Medición de la latencia completa (gesto → movimiento).
* [ ] Respuestas físicas de los 16 módulos según las acciones del juego.

---

## Proyecto SOFIA

Proyecto académico desarrollado como sistema de interacción humano-robot mediante visión por computadora.
