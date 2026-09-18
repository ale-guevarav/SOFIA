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
├── main.py
├── pose_detector.py
├── pose_connections.py
├── hand_detector.py
├── hand_connections.py
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
git clone <URL_DEL_REPOSITORIO>
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

### Próximas etapas

* [ ] Reconocimiento automático de RECARGAR.
* [ ] Reconocimiento automático de ESCUDO.
* [ ] Reconocimiento automático de ATAQUE.
* [ ] Reconocimiento dinámico de INICIO.
* [ ] Reconocimiento dinámico de FIN/DESPEDIDA.
* [ ] Máquina de estados para evitar detecciones repetidas.
* [ ] Implementación de la lógica del juego.
* [ ] Comunicación entre el sistema de visión y SOFIA.
* [ ] Respuestas físicas del robot según las acciones del juego.

---

## Proyecto SOFIA

Proyecto académico desarrollado como sistema de interacción humano-robot mediante visión por computadora.
