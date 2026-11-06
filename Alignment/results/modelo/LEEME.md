# Modelo publicado

Aquí va el modelo que **sí** se sube al repositorio, para que el equipo lo tenga al clonar sin entrenar nada. Los pesos de cada entrenamiento se quedan en `build/entrenados/`, que no se sube.

| Archivo | Qué es |
| --- | --- |
| `cnn.pt` | Pesos de la CNN pequeña (~5 MB) |
| `cnn.json` | De dónde salió: sesión, época y MAE en val |

La app (`Alignment/app/app_diagnostico.py`) y el método híbrido usan `cnn.pt` por defecto.

## Publicar una versión nueva

```
python Alignment/build/publicar_modelo.py
git add Alignment/results/modelo
```

Publica solo cuando el modelo mejore: cada versión subida se queda en el historial de git.

## Para usarlo

- **Con PyTorch instalado** (ver `Alignment/requirements.txt`): la CNN y el híbrido funcionan. Con GPU, ~12 ms por foto; en CPU tarda más pero también funciona.
- **Sin PyTorch:** la app avisa y usa el método geométrico.
