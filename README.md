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
sofia_pose_detection/
│
├── models/
│   ├── pose_landmarker.task
│   └── hand_landmarker.task
│
├── metrics/                  (se crea automáticamente)
│   ├── sesion_*.json
│   └── reportes/
│
├── main.py
├── pose_detector.py
├── pose_connections.py
├── hand_detector.py
├── hand_connections.py
├── gesture_detector.py
├── geometry_utils.py
├── smoothing.py
├── metrics_logger.py
├── generate_report.py
├── requirements.txt
├── .gitignore
└── README.md
```

### `main.py`

Es el punto principal de ejecución del programa.

Se encarga de:

* Inicializar la cámara.
* Obtener los frames.
* Enviar las imágenes a los detectores.
* Coordinar Pose y Hands.
* Mostrar el resultado.
* Calcular los FPS.
* Registrar las métricas de desempeño.
* Liberar los recursos al finalizar.

### `pose_detector.py`

Contiene la lógica relacionada con MediaPipe Pose Landmarker.

Se encarga de detectar y dibujar la estructura corporal.

### `pose_connections.py`

Define las conexiones utilizadas para representar gráficamente el esqueleto corporal.

### `hand_detector.py`

Contiene la lógica relacionada con MediaPipe Hand Landmarker.

Se encarga de detectar y dibujar las manos y sus articulaciones.

### `hand_connections.py`

Define las conexiones entre los 21 landmarks de cada mano.

### `gesture_detector.py`

Contiene las reglas geométricas para reconocer los cinco gestos a partir de los landmarks.

### `geometry_utils.py`

Funciones de apoyo para calcular distancias, ángulos y distancias normalizadas.

### `smoothing.py`

Suavizado de landmarks (EMA) y confirmación temporal para evitar detecciones inestables.

### `metrics_logger.py`

Mide el desempeño del sistema mientras se ejecuta: FPS, latencia por frame y resultados de las pruebas. Guarda todo en un archivo JSON.

### `generate_report.py`

Lee el JSON de métricas y genera el reporte en Excel (`.xlsx`) y Markdown (`.md`) con tablas y gráficas.

### `models/`

Contiene los modelos utilizados por MediaPipe:

```text
pose_landmarker.task
hand_landmarker.task
```

---

# Posturas y gestos propuestos

Para la interacción con SOFIA se diseñaron cinco gestos inspirados en la dinámica del juego **Vaqueritos**.

En esta primera etapa los gestos se encuentran diseñados conceptualmente. Su reconocimiento automático será implementado en una etapa posterior utilizando los landmarks obtenidos por Pose Landmarker y Hand Landmarker.

## 1. INICIO - Tres palmadas

**Tipo:** Gesto dinámico.

La persona coloca las manos cerca de los muslos y realiza tres palmadas consecutivas sobre ellos.

**Función:**

Indicar el inicio de la partida o una transición hacia el modo de juego.

**Detección propuesta:**

Se analizará la distancia entre las muñecas/manos y la zona de los muslos a través de varios frames, utilizando un contador para reconocer tres movimientos consecutivos.

---

## 2. RECARGAR

**Tipo:** Postura estática.

La persona flexiona ambos brazos y coloca las manos aproximadamente a la altura de los hombros.

**Función:**

Recargar munición dentro del juego.

**Detección propuesta:**

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

**Detección propuesta:**

Se analizará la posición relativa de:

* Hombros.
* Codos.
* Muñecas.
* Torso.

Las muñecas deberán encontrarse cruzadas o posicionadas hacia lados opuestos del torso.

---

## 4. ATAQUE

**Tipo:** Postura principalmente estática.

La persona dirige los brazos hacia el frente y realiza con las manos un gesto similar a una pistola.

**Función:**

Realizar un ataque contra SOFIA.

**Detección propuesta:**

Pose Landmarker permitirá analizar la extensión y dirección de los brazos.

Hand Landmarker permitirá analizar individualmente los dedos para identificar una configuración similar a:

* Índice extendido.
* Pulgar extendido.
* Dedos medio, anular y meñique flexionados.

---

## 5. FIN / DESPEDIDA

**Tipo:** Gesto dinámico.

La persona levanta ambas manos y realiza un movimiento lateral de despedida.

**Función:**

Finalizar la interacción o indicar el término de la partida.

**Detección propuesta:**

Se analizará la posición de las manos durante varios frames para detectar cambios repetidos de dirección de izquierda a derecha.

---

# Flujo actual del sistema

```text
Cámara
   │
   ▼
OpenCV
   │
   ├───────────────┐
   ▼               ▼
Pose Landmarker   Hand Landmarker
   │               │
   ▼               ▼
33 landmarks      21 landmarks por mano
   │               │
   └───────┬───────┘
           ▼
Representación visual
           │
           ▼
Esqueleto + manos + FPS
```

---

# Flujo futuro

El sistema está diseñado para evolucionar hacia:

```text
Cámara
   │
   ▼
Pose + Hands
   │
   ▼
Landmarks
   │
   ▼
Detector de gestos
   │
   ├── INICIO
   ├── RECARGAR
   ├── ESCUDO
   ├── ATAQUE
   └── FIN
   │
   ▼
Lógica del juego
   │
   ▼
SOFIA
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

```bash
pip install -r requirements.txt
```

> `requirements.txt` debe incluir `openpyxl` para poder generar el reporte en Excel.

---

# Ejecución

Con el entorno virtual activado:

```bash
python main.py
```

Se abrirá una ventana con la imagen de la cámara y la detección en tiempo real.

Para cerrar el programa:

```text
Presionar Q
```

Al cerrar se guardan automáticamente las métricas de la sesión y se genera el reporte (ver la siguiente sección).

---

# Pruebas y métricas de desempeño

El sistema incluye un modo de pruebas para medir qué tan bien funciona. Las métricas registradas son:

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

Al presionar `q` se crean los siguientes archivos:

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
# Sesión más reciente
python generate_report.py

# Sesión específica
python generate_report.py metrics/sesion_AAAAMMDD_HHMMSS.json
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
* [x] Reconocimiento dinámico de RECARGAR.
* [x] Reconocimiento dinámico de INICIO (tres palmadas).
* [x] Reconocimiento dinámico de FIN/DESPEDIDA.
* [x] Modo de pruebas con cuenta regresiva.
* [x] Registro de métricas de desempeño (tasa de acierto, tiempo de respuesta y FPS promedio).
* [x] Generación de reportes en Excel y Markdown con tablas y gráficas.

### Próximas etapas

* [ ] Máquina de estados para evitar detecciones repetidas.
* [ ] Implementación de la lógica del juego.
* [ ] Comunicación entre el sistema de visión y SOFIA.
* [ ] Respuestas físicas del robot según las acciones del juego.

---

## Proyecto SOFIA

Proyecto académico desarrollado como sistema de interacción humano-robot mediante visión por computadora.
