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
     ──► 16 recortes, uno por hexágono ──► CNN (o geométrico) ──► (θ1, θ2) y estado
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
│       ├── diagnosticador.py       lo que llama la app (CNN, geométrico o híbrido)
│       ├── ceros.py                ángulos de la app -> ceros de los servos (menú Alineación)
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
│   ├── datos/reales/<sesión>/  fotos del módulo real        (no se sube)
│   └── entrenados/<modelo>_<sesión>/  pesos (no se suben), historial y curvas
│
├── results/    LO QUE SALE DEL BUILD Y USA LA APP
│   ├── modelo/cnn.pt           modelo publicado: Webots + fotos reales (sí se sube, ~5 MB)
│   ├── modelo/cnn_sim.pt       modelo anterior, solo Webots (para comparar)
│   ├── evaluaciones/           métricas, gráficas y comparacion.md de cada método
│   ├── COMPARACION.md          geométrico vs CNN vs híbrido
│   ├── marcadores_imprimir.png hoja para el marco del módulo real
│   ├── diagnosticos/           reportes guardados desde la app (no se suben)
│   ├── centros_reales.json     centro de cada placa en el módulo real (fotos alineadas a mano)
│   └── ceros_esp32.json        ceros de los servos (menú Alineación de la GUI de visión)
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

Usa `results/modelo/cnn.pt` con la **CNN** (afinada con fotos del módulo real: 0.23° de error en las fotos reales de test, 0.53° en Webots). Sin PyTorch o sin modelo, avisa y usa el geométrico.

En **Método** se elige: *CNN pequeña* (la publicada), *CNN solo simulación (anterior)* (`cnn_sim.pt`, 2.04° en las fotos reales), *Geométrico* o *Híbrido*. Con la cámara y con fotos reales, los recortes se centran en las placas reales (`results/centros_reales.json`); con sesiones de Webots, en las del diseño.

| Fuente | Cómo |
| --- | --- |
| **Cámara** | *Abrir cámara*. Con todo en 0,0, *Tomar referencia 0,0*; luego *Analizar* o *Continuo* |
| **Fotos / sesión de Webots** | *Abrir carpeta / sesión…* Con una sesión (`build/datos/webots/sesion_…`) también dibuja el valor real (flecha blanca) y el error |
| **Webots en vivo** | Ver abajo |

*■ Cerrar fuente* cierra la cámara o la conexión con Webots. *Guardar reporte* deja imagen + CSV en `results/diagnosticos/`.

### Desde la GUI de visión (menú Alineación)

La GUI de `Vision/` usa este mismo núcleo (`app/nucleo`) en su menú verde **Alineación**: *Tomar ceros* mide las 16 unidades y guarda el cero de cada servo en `results/ceros_esp32.json`; *Alinear* corrige una por una las que no están OK. La GUI manda esos ceros al ESP32 cada vez que se conecta. La conversión de ángulos a grados del servo (signos, ganancia y paso máximo) está en `app/nucleo/ceros.py`. Si una unidad tiene un servo al revés, *Alinear* lo detecta y guarda su signo en el mismo JSON (`signo_x` / `signo_y`). Ver `Vision/README.md`.

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

**Fotos del módulo real:** se arma una sesión con la misma estructura que las de Webots (`imagenes/00000.jpg …` con la foto 0 en 0,0, y `etiquetas.csv` con θ1 y θ2 de cada panel en cada foto), se prepara con `preparar_dataset.py` y se afina la CNN de Webots con `--desde`. Con pocas fotos reales basta, porque la red ya aprendió en la simulación.

Así se hizo `sesion_real_20261126` (el modelo publicado):

1. Se alineó el módulo a mano y se tomaron 7 fotos de referencia en 0,0; de ellas salen los centros reales de cada placa (`results/centros_reales.json`).
2. Con `ESP32/sofia_desalineo_azar/` se mandaron ~400 posiciones al azar y se tomó una foto de cada una (el CSV del monitor guarda los ángulos mandados).
3. Los servos no llegan al ángulo mandado (mueven la placa entre 0 y 40 %), así que la etiqueta **no** es el ángulo mandado: se **midió** en cada foto cuánto se corrió cada placa respecto a las fotos alineadas (comparación de plantillas, subpíxel) y se convirtió a ángulo con la cinemática. El ángulo mandado solo sirvió para emparejar cada foto con su muestra.
4. Se afinó la CNN de Webots con `--desde` y se publicó: 2.04° → **0.23°** en las 60 fotos reales de test, y la exactitud de estados de 72 % a 96 %.

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

1. Más fotos reales (otra luz, otra altura de cámara) para que el modelo no dependa de esta sesión.
2. Revisar los servos que casi no mueven la placa (X de las unidades 2, 3, 7, 8 y 15; Y de la 9): con ellos *Alinear* no puede corregir.
3. Las unidades 10 y 11 (placas plateadas sobre base blanca) se miden peor: pintarlas o cambiar la base.
