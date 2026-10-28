# SOFIA - Diagnóstico visual de alineación

Una cámara ve el módulo de 16 hexágonos y estima, para cada uno, sus dos ángulos (θ1, θ2). Con eso dice **qué hexágono no está en 0,0, cuánto hay que corregir, qué porcentaje de desalineación tiene y su estado**.

| Estado | Desalineación \|θ\| = √(θ1² + θ2²) |
| --- | --- |
| OK | menos de 2° |
| REVISAR | de 2° a 5° |
| DESALINEADO | más de 5° |

Porcentaje = eje más desviado / 30° × 100 (30° es el tope mecánico).

```
Foto ──► 4 marcadores ArUco del marco ──► foto enderezada (vista desde arriba)
     ──► 16 recortes, uno por hexágono ──► geométrico + CNN (híbrido) ──► (θ1, θ2) y estado
```

Comparación de los métodos y resultados: [`results/COMPARACION.md`](results/COMPARACION.md).

## Estructura

```
Alignment/
├── app/        LA APP: lo que corre para diagnosticar
│   ├── app_diagnostico.py      ventana
│   ├── diagnostico_worker.py   hilo (QThread) que lee la fuente y analiza
│   ├── webots_vivo.py          conexión con Webots en vivo
│   └── nucleo/                 lógica del diagnóstico (también la usa build/)
│       ├── geometria.py            TODAS las medidas del módulo y del marco
│       ├── preprocesamiento.py     ArUco -> foto enderezada -> 16 recortes
│       ├── metodo_geometrico.py    método sin entrenamiento
│       ├── modelos.py, inferencia.py   CNN / ResNet18 y cómo usarlas
│       ├── diagnosticador.py       híbrido + lo que llama la app
│       └── rutas.py                dónde está cada carpeta
│
├── build/      DONDE SE ENTRENA (o reentrena)
│   ├── preparar_dataset.py     sesión de Webots -> recortes etiquetados
│   ├── dataset_torch.py        recortes -> PyTorch (aumentos)
│   ├── entrenar.py             entrena la CNN o la ResNet18
│   ├── evaluacion.py           métricas iguales para todos los métodos
│   ├── evaluar_geometrico.py, evaluar_modelo.py, evaluar_hibrido.py
│   ├── comparar_resultados.py  tabla de todos los métodos
│   ├── publicar_modelo.py      copia el modelo bueno a results/modelo/
│   ├── herramientas/           marcadores ArUco y mundos de Webots
│   ├── datos/webots/<sesión>/  fotos de Webots              (no se sube)
│   └── entrenados/<modelo>_<sesión>/  pesos (no se suben), historial y curvas
│
├── results/    LO QUE SALE DEL BUILD Y USA LA APP
│   ├── modelo/cnn.pt           modelo publicado (sí se sube, ~5 MB)
│   ├── evaluaciones/           métricas, gráficas y comparacion.md de cada método
│   ├── COMPARACION.md          geométrico vs PyTorch vs híbrido
│   ├── marcadores_imprimir.png hoja para el marco del módulo real
│   └── diagnosticos/           reportes guardados desde la app (no se suben)
│
└── requirements.txt
```

En Webots (`Webots/Sofia/`):

| Archivo | Qué hace |
| --- | --- |
| `worlds/sofia_dataset.wbt` + `controllers/dataset_generator/` | Genera el dataset |
| `worlds/sofia_diagnostico_vivo.wbt` + `controllers/diagnostico_vivo/` | Conecta la cámara con la app para probar en vivo |
| `controllers/panel_dataset/` | Pone cada unidad (PROTO `sofia`) en un ángulo exacto y la mide con sus sensores (los dos mundos) |

Todo se corre **desde la carpeta `SOFIA`** con el entorno activado.

---

## App

```
python Alignment/app/app_diagnostico.py
```

Usa `results/modelo/cnn.pt` con el método **híbrido**. Sin PyTorch o sin modelo, avisa y usa el geométrico.

| Fuente | Cómo |
| --- | --- |
| **Cámara** | *Abrir cámara*. Con todo en 0,0, *Tomar referencia 0,0*; luego *Analizar* o *Continuo* |
| **Fotos / sesión de Webots** | *Abrir carpeta / sesión…* Con una sesión (`build/datos/webots/sesion_…`) también dibuja el valor real (flecha blanca) y el error |
| **Webots en vivo** | Ver abajo |

*■ Cerrar fuente* cierra la cámara o la conexión con Webots. *Guardar reporte* deja imagen + CSV en `results/diagnosticos/`.

### Webots en vivo

1. En Webots abre `Webots/Sofia/worlds/sofia_diagnostico_vivo.wbt` y dale ▶. En la consola:
   ```
   [VIVO] Esperando la app en 127.0.0.1:5557 (cámara 1280x1280)
   ```
   *(La primera vez compila `panel_dataset` si no lo has hecho: abre `panel_dataset.cpp` y **Build**.)*
2. En la app: **Webots en vivo**. La primera imagen con todo en 0,0 se toma sola como referencia.
3. Mueve los paneles desde el grupo **Webots en vivo**:
   * **Desalinear al azar**: N paneles hasta X°.
   * **Mover panel**: un panel a (θ1, θ2) exactos.
   * **Todo a 0,0**: regresa todo (y vuelve a tomar la referencia).
   * **Cámara y luz al azar / Escena normal**: mueve la cámara y cambia la luz como en el dataset.
4. Cada vez que los paneles se quedan quietos, la app analiza sola y compara contra los ángulos **medidos** en la simulación.

---

## Build

### 1. Dataset en Webots

1. *(Solo si cambiaste `app/nucleo/geometria.py`)*:
   ```
   python Alignment/build/herramientas/generar_marcadores.py
   python Alignment/build/herramientas/crear_mundo_dataset.py
   ```
   (regenera las texturas, `results/marcadores_imprimir.png` y los dos mundos)
2. Abre en Webots `Webots/Sofia/worlds/sofia_dataset.wbt`.
3. Compila los paneles **una vez**: abre `controllers/panel_dataset/panel_dataset.cpp` y presiona **Build**.
4. Cuántas fotos: `DATASET_MUESTRAS` en `controllers/dataset_generator/runtime.ini` (20 para probar, 10 000 para el dataset completo; semilla en `DATASET_SEMILLA`). Con 10 000 fotos ocupa ~8 GB entre fotos, recortes y caché.
5. Dale ▶. Sale en `Alignment/build/datos/webots/sesion_<fecha>/`:

| Archivo | Contenido |
| --- | --- |
| `imagenes/00000.jpg ...` | Fotos de 1280×1280 |
| `referencia.png` | Muestra 0: todos los paneles en 0,0 (para el método geométrico) |
| `etiquetas.csv` | Una fila por panel y foto: θ1, θ2 **medidos**, los mandados, magnitud, % y estado |
| `escenas.csv` | Posición de la cámara, luces y piso de cada foto |
| `config.json` | Geometría y cámara usadas |

En cada foto cambian: **ángulos** de cada panel, como pasaría en el robot (10 % en 0,0; 60 % desalineación mínima, hasta 5°; 20 % notoria, de 5° a 15°, como si lo hubieran movido a mano o se trabara; 10 % muy desalineado, de 15° al tope), **cámara** (±4 cm, 1.30–1.40 m de altura, ±4° de inclinación, ±8° de giro), **luces** y **tono del piso**. Queda ~35 % OK, ~36 % REVISAR y ~29 % DESALINEADO.

### 2. Preparar, entrenar, evaluar y publicar

```
python Alignment/build/preparar_dataset.py               recortes + división train/val/test (por foto)
python Alignment/build/entrenar.py --modelo cnn          (lotes y aumentos en la GPU; también evalúa en test)
python Alignment/build/evaluar_geometrico.py
python Alignment/build/evaluar_hibrido.py
python Alignment/build/comparar_resultados.py            tabla de la última sesión en results/evaluaciones/comparacion.md
python Alignment/build/publicar_modelo.py                copia la última CNN a results/modelo/cnn.pt
```

### Entrenar por partes

`entrenar.py` guarda el estado completo al terminar cada época (`ultimo.pt`), así que no hace falta dejar la PC entrenando todo el día:

```
python Alignment/build/entrenar.py --modelo cnn --minutos 60     para después de ~1 hora
python Alignment/build/entrenar.py --reanudar --minutos 60       otro día: sigue donde se quedó
python Alignment/build/entrenar.py --reanudar                    hasta terminar (y evalúa en test)
```

También se puede parar con **Ctrl+C** en cualquier momento (se pierde solo la época que iba a la mitad). Al reanudar sigue con la misma época, el mismo learning rate y el mismo mejor modelo, como si no se hubiera parado.

### Afinar un modelo (más épocas o fotos reales)

```
python Alignment/build/entrenar.py --desde Alignment/results/modelo/cnn.pt                       10 épocas más
python Alignment/build/entrenar.py --desde Alignment/results/modelo/cnn.pt <sesión> --epocas 15  con otra sesión
```

Empieza con los pesos del modelo y un learning rate 10 veces menor (para ajustar sin "desaprender") y sale en `build/entrenados/<modelo>_<sesión>_afinado/`.

**Fotos del módulo real:** se arma una sesión con la misma estructura que las de Webots (`imagenes/00000.jpg …` con la foto 0 en 0,0, y `etiquetas.csv` con θ1 y θ2 de cada panel en cada foto, por ejemplo mandando ángulos conocidos con el ESP32), se prepara con `preparar_dataset.py` y se afina la CNN de Webots con `--desde`. Con pocas fotos reales basta, porque la red ya aprendió en la simulación.

Todos usan la **última sesión** si no se les pasa otra. Publica (y sube con `git add Alignment/results/modelo`) solo cuando el modelo mejore: cada versión subida se queda en el historial de git.

PyTorch con CUDA:
```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r Alignment/requirements.txt
```

---

## El marco del módulo real

Imprime `results/marcadores_imprimir.png` **al 100 %** (sin "ajustar a la página") y comprueba con regla que el cuadro negro mida 60 mm. Los centros de los 4 marcadores van en un cuadrado de `LADO_MARCO` = **600 mm** (`app/nucleo/geometria.py`), centrado en el arreglo y **a la altura de las placas** con el módulo en 0,0:

```
  ID 0 ─────────── ID 1        (vista desde arriba, como la cámara)
   │                │
   │    módulo 4×4  │
   │                │
  ID 3 ─────────── ID 2
```

Cuando el módulo esté listo hay que medir y actualizar en `geometria.py`: posición de los hexágonos, radio de la placa, altura de las placas, brazo de los ejes y lado del marco. Después se regeneran los mundos y el dataset (Build).

## Siguientes pasos

1. Fotos del módulo real: ajuste fino de la CNN y evaluación.
2. Meter la app como modo **Diagnóstico** en la GUI principal (el hilo ya está hecho igual que el de la GUI).
3. Comparación con el gemelo digital.
