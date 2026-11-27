# SOFIA

Superficie cinética de 16 unidades hexagonales (2 grados de libertad cada una) que responde a los gestos de una persona. Proyecto del Laboratorio de Desarrollo de Soluciones Tecnológicas, ITESO.

| Carpeta | Qué tiene | Léeme |
| --- | --- | --- |
| `Vision/` | Detección de posturas y de la mano (MediaPipe), GUI (PySide6), enlace BLE con el ESP32 y menú **Alineación** | [`Vision/README.md`](Vision/README.md) |
| `Alignment/` | Diagnóstico de alineación con cámara: CNN, método geométrico, app y entrenamiento | [`Alignment/README.md`](Alignment/README.md) |
| `ESP32/` | Firmware del maestro (BLE + 16 unidades) y de los esclavos (RS-485/Modbus); prueba de ángulos al azar | [`ESP32/README.md`](ESP32/README.md) |
| `Webots/` | Simulación de las 16 unidades (gemelo digital) y mundos del dataset de alineación | [`Webots/README.md`](Webots/README.md) |
| `PCB/` | PCB de SOFIA (KiCad) | |
| `Paper-Latex/` | Papers y manual de usuario | |
| `Respuesta revisores/` | Respuestas a los revisores de cada corte | |

```
Cámara de poses ──► Vision (GUI) ──BLE──► ESP32 maestro ──► 16 unidades
                        │   └──TCP──► Webots (simulación)
Cámara del módulo ──► Alineación (CNN de Alignment/) ──► ceros de los servos (AJUSTE)
```

Todo se corre desde esta carpeta con el entorno de Python activado (ver la instalación en cada léeme). Un solo `.gitignore` en la raíz cubre todo el repositorio.
