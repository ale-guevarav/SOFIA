# Diagnóstico de alineación: geométrico vs PyTorch

Los dos métodos hacen lo mismo: reciben la foto del módulo (con los 4 ArUco), la enderezan, sacan los 16 recortes de 128×128 y regresan (θ1, θ2) de cada hexágono. Lo que cambia es **cómo** se sacan los ángulos de cada recorte.

```
Alignment/
├── geometria.py, preprocesamiento.py, evaluacion.py   ← compartido
├── herramientas/   preparar_dataset.py, comparar_resultados.py
├── geometrico/     metodo_geometrico.py, evaluar_geometrico.py
└── pytorch/        datos.py, modelos.py, entrenar.py, evaluar_modelo.py, inferencia.py
```

## 1. Método geométrico (`geometrico/`)

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

## 2. Modelos PyTorch (`pytorch/`)

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

## Resultados (test: 300 fotos = 4800 hexágonos, sesión de 2000 fotos de Webots)

| Método | MAE (°) | RMSE (°) | Error máx (°) | MAE 0-2° | MAE 2-5° | MAE 5-15° | MAE >15° | Exactitud estados | F1 macro | ms/foto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Geométrico | 0.539 | 1.927 | 74.0 | **0.132** | **0.145** | 0.331 | 1.301 | **97.2 %** | **0.967** | 32 (CPU) |
| CNN pequeña | **0.248** | **0.347** | 4.4 | 0.176 | 0.189 | **0.246** | **0.363** | 96.3 % | 0.957 | **12** (GPU) |
| ResNet18 | 0.293 | 0.409 | **4.1** | 0.225 | 0.204 | 0.298 | 0.433 | 95.9 % | 0.952 | 16 (GPU) |

Entrenamiento en una RTX 3060: CNN 40 épocas (84 min), ResNet18 25 épocas (24 min).

**Lo que dicen los números**

- **La CNN pequeña es la mejor en general:** error promedio 2.2 veces menor que el geométrico y sin errores catastróficos (máximo 4.4° contra 74° del geométrico).
- **El geométrico sigue ganando en ángulos chicos (0-5°)** y por eso tiene la mejor exactitud de estados: los umbrales OK / REVISAR / DESALINEADO (2° y 5°) caen justo donde es más preciso.
- **El geométrico falla en ángulos grandes (>15°):** MAE 1.3° y casos aislados muy malos, cuando confunde la placa con el hueco del vecino.
- **ResNet18 no supera a la CNN** aunque es 10 veces más grande: lo que aprendió en ImageNet (objetos, texturas) no ayuda mucho a medir un desplazamiento de pocos píxeles. Seguía mejorando en la última época, así que con más épocas podría acercarse.
- **Los tres se equivocan más en θ1 que en θ2.**
- **Todo es en simulación:** falta confirmarlo con fotos del módulo real.

La tabla completa (con p95 y recall de "necesita atención") se genera con:

```
python Alignment/herramientas/comparar_resultados.py
```

## Cuándo usar cuál

- **Sin GPU o sin datos del módulo real todavía:** geométrico.
- **Con GPU:** la CNN pequeña es la mejor opción individual.
- **Propuesta (híbrido):** usar el geométrico para decidir el estado en ángulos chicos y la CNN como verificación. Si los dos difieren mucho en un hexágono, se toma el valor de la CNN y se marca para revisar. Así se combina la precisión del geométrico cerca de los umbrales con la robustez de la CNN.
