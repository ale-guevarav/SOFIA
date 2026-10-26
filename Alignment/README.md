# SOFIA - Diagnóstico visual de alineación

Una cámara ve el módulo de 16 hexágonos y estima, para cada uno, sus dos ángulos (θ1, θ2). Con eso dice **qué hexágono no está en 0,0, cuánto hay que corregir, qué porcentaje de desalineación tiene y su estado**.

| Estado | Desalineación \|θ\| = √(θ1² + θ2²) |
| --- | --- |
| OK | menos de 2° |
| REVISAR | de 2° a 5° |
| DESALINEADO | más de 5° |

Porcentaje = \|θ\| / 30° × 100 (30° es el tope mecánico).

## Cómo funciona

```
Foto ──► 4 marcadores ArUco del marco ──► foto enderezada (vista desde arriba)
     ──► 16 recortes, uno por hexágono ──► modelo ──► (θ1, θ2) de cada hexágono
```

Se comparan tres métodos:

| Método | Idea |
| --- | --- |
| Geométrico (línea base) | Cuánto se corrió el centro de cada placa respecto a la foto de referencia en 0,0: θ ≈ asin(d / L) |
| CNN pequeña | Red entrenada desde cero con los recortes |
| ResNet18 | Red preentrenada, ajustada con los recortes |

Se entrena con imágenes de **Webots** (ángulos exactos) y se ajusta y evalúa con fotos del **módulo real**.

## Estructura

| Archivo | Qué hace |
| --- | --- |
| `geometria.py` | **Todas las medidas** (posición de los hexágonos, marco, alturas, resolución, umbrales). Si cambia el módulo, se cambia aquí. |
| `herramientas/generar_marcadores.py` | Texturas ArUco para Webots y hoja para imprimir (`marcadores_imprimir.png`) |
| `herramientas/crear_mundo_dataset.py` | Crea `Webots/Sofia/worlds/sofia_dataset.wbt` a partir del mundo normal |
| `datos/` | Imágenes y etiquetas generadas (no se suben a git) |

En Webots: `controllers/panel_dataset/` pone cada panel en un ángulo exacto y lo mide con un sensor; `controllers/dataset_generator/` cambia la escena, toma las fotos y guarda las etiquetas.

## Paso 1: generar el dataset en Webots

1. *(Solo si cambiaste `geometria.py`)* desde la carpeta `SOFIA`, con el entorno activado:
   ```
   python Alignment/herramientas/generar_marcadores.py
   python Alignment/herramientas/crear_mundo_dataset.py
   ```
2. Abre en Webots `Webots/Sofia/worlds/sofia_dataset.wbt`.
3. Compila los paneles **una vez**: abre `controllers/panel_dataset/panel_dataset.cpp` y presiona **Build**.
4. Cuántas fotos: en `controllers/dataset_generator/runtime.ini`, `DATASET_MUESTRAS`. Viene en **20** para probar; para el dataset completo pon **2000**.
5. Dale ▶. Webots se pone en modo rápido y en la consola va saliendo:
   ```
   [DATASET] 20 muestras -> ...\Diagnostico\datos\webots\sesion_...
   [DATASET] 1/20 (1 guardadas, 0 s)
   ...
   [DATASET] Listo: 20 imágenes en ...
   ```
6. El resultado queda en `Alignment/datos/webots/sesion_<fecha>/`:

| Archivo | Contenido |
| --- | --- |
| `imagenes/00000.jpg ...` | Fotos de 1280×1280 |
| `referencia.png` | Muestra 0: todos los paneles en 0,0 (para el método geométrico) |
| `etiquetas.csv` | Una fila por panel y foto: θ1, θ2 **medidos**, los mandados, magnitud, % y estado |
| `escenas.csv` | Posición de la cámara, luces y piso de cada foto |
| `config.json` | Geometría y cámara usadas |

### Qué cambia en cada foto

* **Ángulos**: 5 % de los paneles exactamente en 0,0, 50 % casi alineados (±3°) y el resto en todo el rango (±27°).
* **Cámara**: ±4 cm de desplazamiento, 1.30–1.40 m de altura, ±4° de inclinación y ±8° de giro (el marco siempre queda completo en la foto).
* **Luces**: intensidad y dirección al azar.
* **Piso**: tono de gris al azar.

## El marco del módulo real

Imprime `marcadores_imprimir.png` **al 100 %** (sin "ajustar a la página") y comprueba con regla que el cuadro negro mida 60 mm. Los centros de los 4 marcadores van en un cuadrado de `LADO_MARCO` (geometria.py), **a la altura de las placas** con el módulo en 0,0:

```
  ID 0 ─────────── ID 1        (vista desde arriba, como la cámara)
   │                │
   │    módulo 4×4  │
   │                │
  ID 3 ─────────── ID 2
```

Cuando el módulo esté listo hay que medir y actualizar en `geometria.py`: posición de los hexágonos, radio de la placa, altura de las placas, brazo de los ejes y lado del marco. Después se regeneran el mundo y el dataset.

## Siguientes pasos

2. Preprocesamiento: detectar los ArUco, enderezar y recortar.
3. Método geométrico y su evaluación.
4. Entrenamiento de la CNN pequeña y la ResNet18 (PyTorch con CUDA).
5. Fotos reales: ajuste fino y evaluación.
6. Modo Diagnóstico en la GUI y comparación con el gemelo digital.
