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

## Resultados (test, sesión de 2000 fotos)

| Método | MAE (°) | Exactitud estados | F1 macro | ms/foto |
| --- | --- | --- | --- | --- |
| Geométrico | 0.539 | 97.2 % | 0.967 | 28 |
| CNN pequeña | pendiente | | | |
| ResNet18 | pendiente | | | |

La tabla completa (con error por rango y error máximo) se genera con:

```
python Alignment/herramientas/comparar_resultados.py
```

## Cuándo usar cuál

- **Sin datos del módulo real todavía:** geométrico.
- **Con fotos reales para ajustar:** el mejor modelo PyTorch, y el geométrico como respaldo / verificación (si los dos difieren mucho en un hexágono, se marca para revisar).
