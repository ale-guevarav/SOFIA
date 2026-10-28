# Diagnóstico de alineación: geométrico vs PyTorch

Los métodos hacen lo mismo: reciben la foto del módulo (con los 4 ArUco), la enderezan, sacan los 16 recortes de 128×128 y regresan (θ1, θ2) de cada hexágono. Lo que cambia es **cómo** se sacan los ángulos de cada recorte.

```
Alignment/
├── app/       la app y el núcleo del diagnóstico (geométrico, CNN, híbrido)
├── build/     generar el dataset, entrenar, evaluar y publicar
└── results/   modelo publicado, evaluaciones y este documento
```

## 1. Método geométrico (`app/nucleo/metodo_geometrico.py`)

Ubica cada placa (binarización + plantilla hexagonal + centroide), mide cuánto se corrió respecto a la foto de referencia en 0,0 y con la cinemática de la unidad lo convierte en ángulos.

**Fuertes**
- No necesita entrenamiento ni datos: funciona desde el primer día con el módulo real.
- Explicable: cada grado sale de una fórmula (se puede mostrar en la presentación).
- Ligero: solo OpenCV, corre en cualquier PC (~21 ms por foto). Es el respaldo de la app sin PyTorch.

**Débiles**
- Su precisión depende del **brazo** (distancia de los ejes a la placa): con el PROTO es de 37 mm, así que 1 píxel de error vale ~1.5°. Por eso su error en ángulos chicos subió de 0.13° a 0.32°.
- Depende de que la placa se vea limpia: sombras, reflejos o cables encima rompen la binarización.
- No corrige la perspectiva al inclinarse (la placa baja un poco): error mayor en ángulos grandes (1.6° arriba de 15°).
- Si cambia el diseño del módulo hay que reajustar umbrales a mano.

## 2. CNN pequeña (`app/nucleo/modelos.py`, entrenada con `build/entrenar.py`)

Una red aprende directo del recorte a los ángulos con las fotos de Webots. Es el **método principal** de la app.

**Fuertes**
- La más precisa en **todos** los rangos y sin errores grandes.
- Aprende sola los efectos que la fórmula ignora (perspectiva, sombras, la placa que baja).
- Más robusta a luz y ruido gracias a los aumentos (brillo, gamma, desenfoque, ruido).
- Con GPU es rápida (13 ms por foto) y procesa los 16 hexágonos en un solo lote.
- Se puede afinar con fotos reales del módulo (`entrenar.py --desde`).

**Débiles**
- Necesita datos etiquetados; los de Webots no son idénticos al módulo real (hay que afinar con fotos reales).
- Si cambia el módulo hay que reentrenar: con el PROTO, la CNN vieja daba ángulos ~30 % más chicos (brazo y recorte distintos) y 1.6° de error.
- Caja negra: es difícil explicar por qué dio un número.
- PyTorch + GPU para que sea rápida; en CPU tarda más.

**ResNet18:** en el experimento con los paneles anteriores, una ResNet18 preentrenada (13.3 M parámetros, 10 veces más grande) no superó a la CNN pequeña (0.293° vs 0.248°); no se reentrenó para el dataset final.

## 3. Método híbrido (`app/nucleo/diagnosticador.py`)

Corre los dos y, para cada hexágono: si difieren más de **2°** usa la CNN y lo marca con "?"; si coinciden y la CNN dice que está a **6° o menos** de 0,0 usa el geométrico; si no, la CNN.

Se pensó cuando el geométrico era el más preciso en ángulos chicos. **Con el PROTO ya no ayuda**: la CNN le gana también ahí, así que el híbrido queda peor que la CNN sola. Se conserva en la app para comparar.

## Resultados (unidades PROTO `sofia`)

Test: **1500 fotos = 24 000 hexágonos** de la sesión de 10 000 fotos (semilla 11), que ningún modelo vio al entrenar.

| Método | MAE (°) | RMSE (°) | Error máx (°) | MAE 0-2° | MAE 2-5° | MAE 5-15° | MAE >15° | Exactitud estados | F1 macro | ms/foto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Geométrico | 0.521 | 0.784 | 5.88 | 0.316 | 0.361 | 0.646 | 1.597 | 94.1 % | 0.943 | 21 (CPU) |
| **CNN pequeña** | **0.204** | **0.280** | **3.28** | **0.148** | **0.190** | **0.228** | **0.406** | **96.8 %** | **0.969** | **13** (GPU) |
| Híbrido | 0.329 | 0.421 | 3.28 | 0.316 | 0.361 | 0.253 | 0.406 | 94.1 % | 0.943 | 31 (CPU + GPU) |

CNN: 25 épocas (mejor en la 24), ~10 min por época en una RTX 3060 con lotes y aumentos en la GPU; MAE en val 0.205°. "¿Necesita atención?" (REVISAR o DESALINEADO): precisión 98.6 %, recall 97.8 %.

**Lo que dicen los números**

- **La CNN es la mejor en todo:** error promedio 2.5 veces menor que el geométrico, la mejor en cada rango y su peor caso es 3.3° en 24 000 hexágonos. Mejora al modelo anterior (0.248°) con un problema más difícil (placa más chica, brazo más corto, más desalineaciones grandes).
- **El geométrico perdió precisión con el PROTO** (0.32° en ángulos chicos, antes 0.13°) porque el brazo es más corto, pero **ya no tiene errores catastróficos** (máximo 5.9°, antes 74°): con las unidades más juntas y la placa más chica ya no se confunde con el hueco del vecino.
- **El híbrido queda peor que la CNN** (0.329°): usa el geométrico justo en los ángulos chicos, donde ahora es el doble de impreciso. De sus 901 "?", 873 eran errores del geométrico y no de la CNN, así que tampoco sirve como verificación de la CNN.
- **Todo es en simulación:** falta confirmarlo con fotos del módulo real.

### Antes del PROTO (paneles anteriores, 2000 fotos)

Test de 300 fotos = 4800 hexágonos. Se conserva como historia; no se mezcla con la tabla de arriba.

| Método | MAE (°) | Error máx (°) | MAE 0-2° | MAE >15° | Exactitud estados |
| --- | --- | --- | --- | --- | --- |
| Geométrico | 0.539 | 74.0 | 0.132 | 1.301 | 97.2 % |
| CNN pequeña | 0.248 | 4.4 | 0.176 | 0.363 | 96.3 % |
| ResNet18 | 0.293 | 4.1 | 0.225 | 0.433 | 95.9 % |
| Híbrido | 0.223 | 4.4 | 0.132 | 0.363 | 97.2 % |

La tabla completa (con p95 y recall de "necesita atención") se genera con:

```
python Alignment/build/comparar_resultados.py
```

## Cuándo usar cuál

- **Con PyTorch (de preferencia con GPU):** la **CNN**. Es la que usa la app por defecto.
- **Sin PyTorch o sin modelo:** geométrico (la app cambia sola y lo avisa).
- **Híbrido:** solo para comparar.
