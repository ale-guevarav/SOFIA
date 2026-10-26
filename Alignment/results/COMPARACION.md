# Diagnóstico de alineación: geométrico vs PyTorch

Los dos métodos hacen lo mismo: reciben la foto del módulo (con los 4 ArUco), la enderezan, sacan los 16 recortes de 128×128 y regresan (θ1, θ2) de cada hexágono. Lo que cambia es **cómo** se sacan los ángulos de cada recorte.

```
Alignment/
├── app/       la app y el núcleo del diagnóstico (geométrico, CNN, híbrido)
├── build/     generar el dataset, entrenar, evaluar y publicar
└── results/   modelo publicado, evaluaciones y este documento
```

## 1. Método geométrico (`app/nucleo/metodo_geometrico.py`)

Ubica cada placa (binarización + plantilla hexagonal + centroide), mide cuánto se corrió respecto a la foto de referencia en 0,0 y con la cinemática del panel lo convierte en ángulos.

**Fuertes**
- No necesita entrenamiento ni datos: funciona desde el primer día con el módulo real.
- Explicable: cada grado sale de una fórmula (se puede mostrar en la presentación).
- Muy preciso en ángulos chicos (≈0.13–0.15° de MAE en 0–5°), que es justo donde se decide OK / REVISAR.
- Ligero: solo OpenCV, corre en cualquier PC (~28 ms por foto).

**Débiles**
- Depende de que la placa se vea limpia: sombras, reflejos o cables encima rompen la binarización.
- Errores grandes de vez en cuando con mucha inclinación (>23°), cuando la placa se confunde con el hueco del vecino (hasta ~74° de error).
- No corrige la perspectiva al inclinarse (la placa baja ~1 cm a 27°): sesgo en ángulos grandes.
- Si cambia el diseño del módulo hay que reajustar umbrales a mano.

## 2. Modelos PyTorch (`app/nucleo/modelos.py`, entrenados con `build/entrenar.py`)

Una red aprende directo del recorte a los ángulos con las 2000 fotos de Webots. Se comparan dos: una **CNN pequeña** desde cero y una **ResNet18** preentrenada.

**Fuertes**
- Aprende sola los efectos que la fórmula ignora (perspectiva, sombras, la placa que baja).
- Más robusta a luz y ruido gracias a los aumentos (brillo, gamma, desenfoque, ruido).
- Con GPU es rápida y procesa los 16 hexágonos en un solo lote.
- Se puede mejorar con fotos reales del módulo (fine-tuning) sin cambiar código.

**Débiles**
- Necesita datos etiquetados; los de Webots no son idénticos al módulo real (hay que ajustar con fotos reales).
- Caja negra: es difícil explicar por qué dio un número.
- Más pesada: PyTorch + GPU para que sea rápida; en CPU tarda más.
- Puede fallar en casos que no vio en el entrenamiento, sin avisar.

## 3. Método híbrido (`app/nucleo/diagnosticador.py`)

Corre los dos y, para cada hexágono:

1. Si difieren más de **2°**, usa la CNN y lo marca con "?" (el geométrico probablemente se confundió).
2. Si coinciden y la CNN dice que está a **6° o menos** de 0,0, usa el geométrico (más preciso cerca de los umbrales).
3. Si no, usa la CNN.

## Resultados (test: 300 fotos = 4800 hexágonos, sesión de 2000 fotos de Webots)

| Método | MAE (°) | RMSE (°) | Error máx (°) | MAE 0-2° | MAE 2-5° | MAE 5-15° | MAE >15° | Exactitud estados | F1 macro | ms/foto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Geométrico | 0.539 | 1.927 | 74.0 | **0.132** | **0.145** | 0.331 | 1.301 | **97.2 %** | **0.967** | 32 (CPU) |
| CNN pequeña | 0.248 | 0.347 | 4.4 | 0.176 | 0.189 | 0.246 | **0.363** | 96.3 % | 0.957 | **12** (GPU) |
| ResNet18 | 0.293 | 0.409 | **4.1** | 0.225 | 0.204 | 0.298 | 0.433 | 95.9 % | 0.952 | 16 (GPU) |
| **Híbrido** | **0.223** | **0.324** | 4.4 | **0.132** | **0.145** | **0.244** | **0.363** | **97.2 %** | **0.967** | 32 (CPU + GPU) |

Entrenamiento en una RTX 3060: CNN 40 épocas (84 min), ResNet18 25 épocas (24 min).

**Lo que dicen los números**

- **El híbrido es el mejor o empata en todo** salvo el tiempo: el error más bajo (0.223°), la precisión del geométrico en ángulos chicos, la de la CNN en ángulos grandes y ningún error catastrófico (máximo 4.4°, el mismo de la CNN).
- **La regla funciona como se pensó:** el geométrico se usó en 2792 de 4800 hexágonos (58 %). Se marcaron 286 desacuerdos y 250 de ellos (87 %) eran de verdad un error del geométrico mayor a 2°. De los 332 errores así del geométrico se atraparon 250; los otros 82 son casos donde el híbrido ya usaba la CNN (fuera de la zona de 6°) o donde los dos coincidían en menos de 2°. Ningún error catastrófico llegó al resultado: el error máximo del híbrido (4.4°) es el mismo de la CNN.
- **La CNN pequeña es el mejor método individual:** error promedio 2.2 veces menor que el geométrico y sin errores catastróficos (máximo 4.4° contra 74°).
- **El geométrico gana en ángulos chicos (0-5°)**, donde están los umbrales OK / REVISAR / DESALINEADO, pero falla en ángulos grandes (>15°) cuando confunde la placa con el hueco del vecino.
- **ResNet18 no supera a la CNN** aunque es 10 veces más grande: lo que aprendió en ImageNet no ayuda mucho a medir un desplazamiento de pocos píxeles.
- **Todos se equivocan más en θ1 que en θ2.**
- **Todo es en simulación:** falta confirmarlo con fotos del módulo real.

La tabla completa (con p95 y recall de "necesita atención") se genera con:

```
python Alignment/build/comparar_resultados.py
```

## Cuándo usar cuál

- **Con PyTorch (de preferencia con GPU):** el **híbrido**. Es el que usa la app por defecto.
- **Solo la CNN:** si importa la velocidad (12 ms contra 32 ms por foto).
- **Sin PyTorch o sin modelo:** geométrico (la app cambia sola y lo avisa).
