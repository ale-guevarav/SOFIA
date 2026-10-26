# SOFIA - Simulación en Webots (clon citual)

Simulación del arreglo de **16 paneles de 2 grados de libertad** (`motor_gdl1` y `motor_gdl2`, ±30°) que apuntan a una esfera. La GUI de visión se conecta a la simulación con **el mismo protocolo** que usa con el ESP32 por Bluetooth, así se prueba todo sin hardware.

```
GUI (Vision/gui_app.py)
 ├─ Hilo de enlace (WebotsLink) ──TCP :5555──► sofia_maestro_sim (esfera)
 │      mismas tramas: SOF|TIPO|SEQ|LEN|DATOS|CRC-8, ACK/NACK           │ customData
 │                                                                       ▼
 │                                                    16 × tracker_esfera_cpp (paneles)
 │
 └─ Hilo cámara sim (SimCameraClient) ◄──TCP :5556── camara_sim (cámara cenital)
```

* La **visión no se procesa en Webots**: la cámara real y MediaPipe siguen en la GUI.
* El **enlace de comandos** es un hilo aparte, igual que el BLE.
* La **cámara virtual** es su propio nodo, con su propio controlador y su propio puerto. Si se apaga, nada más se entera.

## Estructura

| Archivo | Qué hace |
| --- | --- |
| `Sofia/worlds/sofia.wbt` | Mundo: 16 paneles, la esfera (maestro) y la cámara cenital |
| `controllers/sofia_maestro_sim/` | **Maestro** (Python), corre en la esfera. Hace lo mismo que el firmware del ESP32: valida tramas, contesta ACK/NACK, ignora duplicados y pasa a estado seguro. Reusa `Vision/comunicacion/protocol.py`. |
| `controllers/tracker_esfera_cpp/` | **Paneles** (C++). Apuntan a la esfera; si llega una postura, dibujan su patrón (`patrones.hpp`). |
| `controllers/camara_sim/` | **Cámara cenital** (Python). Solo manda imágenes a la GUI. |
| `controllers/esfera_control/` | Controlador original (la esfera se mueve sola). Ya no lo usa el mundo; se deja como referencia. |

## Qué hace cada comando

| Comando | En la simulación |
| --- | --- |
| `TRACK` (modo TRACKING) | La esfera va a la posición de tu mano y los 16 paneles la siguen |
| `POSE` | Los paneles dibujan el patrón de la postura (ver abajo) |
| `MODE` | Al entrar o salir de TRACKING, la esfera vuelve al centro |
| `STOP` / estado seguro | Esfera al centro, sin patrón (3 s sin tramas o al desconectar) |
| Sin GUI | La esfera se queda quieta en el centro |

### Patrones por postura

Vistos desde la cámara cenital:

| Postura | Patrón |
| --- | --- |
| INICIO | Arriba-abajo, todos al unísono |
| RECARGAR | "Círculo de carga": solo los 12 paneles del borde, uno tras otro, inclinándose hacia afuera (2 vueltas, sentido horario) |
| ESCUDO | Rombo, todos al unísono |
| ATAQUE | Una L, todos al unísono |
| FIN | Izquierda-derecha (despedida), todos al unísono |

Las figuras, la amplitud y las velocidades se cambian en `controllers/tracker_esfera_cpp/patrones.hpp`.

## Cómo usarlo

1. **La carpeta `Webots/` debe quedarse dentro del repositorio SOFIA.** El maestro busca `Vision/comunicacion/protocol.py` subiendo carpetas; si la mueves a otro lado, define la variable de entorno `SOFIA_PROTOCOL` con la ruta a ese archivo.
2. **Python en Webots.** El maestro y la cámara son controladores de Python y solo usan la biblioteca estándar, no hace falta instalar nada. Si Webots no encuentra Python, ve a *Tools → Preferences → General → Python command* y pon la ruta de tu `python.exe`.
3. **Compilar los paneles (una vez).** Abre `tracker_esfera_cpp.cpp` en el editor de Webots y presiona **Build**, el ícono del engrane, o usa *Build → Clean & Build*.
4. Abre `Sofia/worlds/sofia.wbt` y **corre la simulación** (▶). En la consola debe salir:
   ```
   [MAESTRO] Esperando la GUI en 127.0.0.1:5555...
   [CAMARA] 320x320 en 127.0.0.1:5556
   ```
5. En la GUI (`python gui_app.py` desde `Vision/`), en el panel **Robot**:
   - En la fila **Webots (sim)** presiona **Conectar**.
   - Marca **Ver cámara de Webots** para ver la vista cenital junto al video.
   - *(Opcional)* Marca **Simular canal BLE en Webots** para agregar retraso (~30 ms), pérdidas (3 %) y bytes dañados (2 %), como un enlace Bluetooth real. Así se ven los reintentos y los NACK en la bitácora.
6. Inicia la detección: en **Juego** cada postura hace su patrón y en **Tracking** la esfera sigue tu mano.

### Simulación sola o gemelo digital

La GUI manda los resultados a **todos los destinos conectados**:

| Conectado | Qué pasa |
| --- | --- |
| Solo **Webots** | Simulación sin ESP32: tracking y posturas en la sim |
| Solo **ESP32** | Robot real |
| **Los dos** | **Gemelo digital**: cada comando (POSE, TRACK, MODE, STOP) va al robot real y a la simulación al mismo tiempo |

En la bitácora cada mensaje dice de qué destino viene (`[ESP32]` o `[Webots]`), con el tiempo de su ACK, así se comparan las dos respuestas.

## Ajustes rápidos

* **La esfera se mueve al revés que tu mano:** en `sofia_maestro_sim.py` cambia `INVERTIR_X` o `INVERTIR_Y` a `True`.
* **Qué tanto recorre la esfera:** `RANGO_TRACK` (metros con la mano en el borde de la imagen).
* **Resolución o FPS de la cámara:** `width`/`height` del nodo `Camera` en el mundo y `PERIODO_MS` en `camara_sim.py`.
* **Puertos:** `5555` (comandos) y `5556` (cámara). Si cambias alguno, cámbialo también en `Vision/comunicacion/sim_link.py` o en `Vision/interfaz/sim_camera.py`.
