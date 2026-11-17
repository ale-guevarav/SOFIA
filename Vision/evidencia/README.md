# Evidencia de la integración PC ↔ ESP32

| Archivo o carpeta | Qué es |
|---|---|
| `errores_encontrados.csv` | Los 11 errores encontrados (E-01 a E-11): condición, cómo se detectó, estrategia y verificación |
| `evidencias_pruebas.csv` | Cada prueba con su resultado y datos medidos; las pendientes están marcadas |
| `prueba_sim_2026-11-06/` | Prueba automática de comunicación y estrés con el código ya corregido |
| `prueba_sim_2026-11-06_antes_de_corregir/` | La primera corrida, que encontró los errores E-10 y E-11 |

Cada carpeta de prueba tiene:

- `resultados.json`: los números de cada escenario (S1 a S7).
- `comandos.csv`, `eventos.csv`, `bitacora.txt`, `resumen.md`: el registro de la GUI.
- `salida_prueba.txt`: lo que hicieron la PC y el robot simulado, con la hora.

La prueba se repite con:

```
cd Vision
python -m evaluacion.prueba_comunicacion_sim
```

Usa el enlace de la GUI y el controlador de la simulación (`Webots/Sofia/controllers/sofia_maestro_sim`) sin abrir Webots, sin cámara y sin ESP32. Los escenarios están descritos al inicio de `evaluacion/prueba_comunicacion_sim.py`.

Las sesiones de la GUI con cámara y Webots (ciclo con la webcam, varias personas, iluminación) se copian aquí desde `metrics/sesiones/`.
