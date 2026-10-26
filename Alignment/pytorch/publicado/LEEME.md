# Modelo publicado

Aquí va el modelo que **sí** se sube al repositorio, para que el equipo lo tenga al clonar sin entrenar nada. Las demás versiones se quedan en `entrenados/`, que no se sube.

| Archivo | Qué es |
| --- | --- |
| `cnn.pt` | Pesos de la CNN pequeña (~5 MB) |
| `cnn.json` | De dónde salió: sesión, época y MAE en val |

La app (`Alignment/app/app_diagnostico.py`) y el método híbrido usan `cnn.pt` por defecto.

## Publicar una versión nueva

```
python Alignment/pytorch/publicar_modelo.py
git add Alignment/pytorch/publicado
```

Publica solo cuando el modelo mejore: cada versión subida se queda en el historial de git.

## Para usarlo

- **Con PyTorch instalado** (ver `../requirements.txt`): la CNN y el híbrido funcionan. Con GPU, ~12 ms por foto; en CPU tarda más pero también funciona.
- **Sin PyTorch:** la app avisa y usa el método geométrico.
