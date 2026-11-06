# Pruebas de integración PC ↔ ESP32 (sOFIa)

Este documento es la guía para la etapa de integración. Dice cómo correr las pruebas del ciclo **detección → comando → ESP32 → acción**, cómo hacer las pruebas de estrés y qué hace el sistema ante cada error. Las tablas en blanco se llenan con lo que genera la GUI.

---

## 1. Qué ya hace el sistema

| Actividad | Dónde está | Estado |
|---|---|---|
| Protocolo PC/ESP32 (5 posturas + respuesta) | `comunicacion/protocol.py`, `ble_link.py`, firmware `ESP32/sofia_maestro` | Hecho: tramas con CRC-8, ACK/NACK, reintentos con el mismo SEQ, duplicados ignorados |
| Integración en la GUI | `gui_app.py` | Hecho: cada postura nueva se envía sola; la respuesta se ve en la bitácora |
| Manejo de errores y reconexión | `ble_link.py`, `interfaz/vision_worker.py`, `gui_app.py` | Hecho: ver la sección 5 |
| Evidencia de las pruebas | `evaluacion/session_logger.py` | Automática: CSV + resumen por condición |

---

## 2. Registro automático de la sesión

Al abrir la GUI se crea la carpeta `Vision/metrics/sesiones/sesion_AAAAMMDD_HHMMSS/` con:

| Archivo | Contenido |
|---|---|
| `posturas.csv` | Cada cambio de postura detectada: hora, condición, postura, si había persona, tiempo de procesamiento |
| `comandos.csv` | Cada comando enviado: destino, postura, SEQ, ACK sí/no, intentos, `rtt_ms`, `cola_ms`, `ciclo_ms`, causa si falló |
| `eventos.csv` | Conexiones, caídas, reintentos, reconexiones, fallas de cámara, errores |
| `bitacora.txt` | Copia de la bitácora de la GUI con la hora |
| `resumen.md` / `resumen.json` | Tablas listas para el reporte, separadas por condición |

**Condición de prueba.** Arriba de la bitácora hay un campo de texto. Antes de cada prueba se escribe la condición (ej. `ciclo INICIO`, `luz baja`, `2 personas`) y se presiona Enter. Cada fila lleva esa condición y el resumen sale con una fila por condición. **Guardar resumen** escribe el resumen en ese momento; también se escribe al cerrar la GUI.

**Latencias.**

- `rtt_ms`: desde que se envía la trama hasta que llega el ACK.
- `cola_ms`: desde que la GUI pide el comando hasta el ACK. Incluye la espera en la cola y los reintentos.
- `ciclo_ms`: procesamiento del frame + `cola_ms`. Es el ciclo completo, desde la imagen hasta que el ESP32 confirma.

> El ACK confirma que el ESP32 **recibió y aceptó** el comando. Que el robot **ejecutó** la acción se comprueba viéndolo (video) y en el Monitor Serie del ESP32, que imprime cada `[POSE]`.

---

## 3. Prueba del ciclo detección → acción (actividad 3)

**Preparación**

1. Enciende el ESP32 y abre el Monitor Serie (115200).
2. Corre `python gui_app.py`, conecta el **ESP32** y presiona **PING**: debe salir `✔ PING: ACK en … ms`.
3. Elige el modo **Juego** y presiona **Iniciar**.
4. Graba en video la pantalla y el robot al mismo tiempo (celular o grabador de pantalla con la cámara visible).

**Procedimiento por postura** (repetir para las 5)

1. Escribe la condición `ciclo <POSTURA>` (ej. `ciclo ESCUDO`) y presiona Enter.
2. Haz la postura, mantenla hasta que el robot termine el movimiento y regresa a una posición neutra.
3. Repite 10 veces.

**Acción esperada en sOFIa**

| # | Postura | Acción |
|---|---|---|
| 1 | INICIO | círculo |
| 2 | RECARGAR | cuadrado |
| 3 | ESCUDO | X |
| 4 | ATAQUE | línea arriba-abajo |
| 5 | FIN | zigzag izquierda a derecha |

**Tabla de resultados** (las columnas 3 a 7 salen de `resumen.md`; la 8 se llena viendo el video)

| Postura | Repeticiones | Detectada | Enviados | ACK | Ciclo prom. (ms) | Ciclo p95 (ms) | Acción correcta |
|---|---|---|---|---|---|---|---|
| INICIO | 10 | | | | | | / 10 |
| RECARGAR | 10 | | | | | | / 10 |
| ESCUDO | 10 | | | | | | / 10 |
| ATAQUE | 10 | | | | | | / 10 |
| FIN | 10 | | | | | | / 10 |

**Criterio de éxito.** Cada postura se detecta, su comando recibe ACK y el robot hace la acción correcta en al menos 9 de 10 intentos.

---

## 4. Pruebas de estrés (actividad 4)

Cada condición lleva su propia etiqueta. Al final, **Guardar resumen**.

| Etiqueta | Cómo hacerla | Qué se observa |
|---|---|---|
| `base` | 1 persona, luz normal, posturas pausadas | Referencia para comparar |
| `2 personas` | Dos personas en cuadro, una hace las posturas | ¿A quién sigue? ¿Hay posturas falsas? |
| `3 personas` | Tres personas, se cruzan por detrás | Igual que la anterior |
| `cambios rápidos` | Cambiar de postura cada ~1 s durante 1 min | Comandos en cola, reintentos, que el robot no se trabe |
| `luz baja` | Apagar una parte de la luz | Detecciones perdidas o falsas |
| `contraluz` | Ventana o lámpara detrás de la persona | Igual |
| `luz cambiante` | Prender y apagar la luz durante la prueba | Igual |
| `distancia` | Alejarse hasta 2–3 m del ESP32 | RTT, reintentos, caídas del enlace |
| `ESP32 reinicio` | Presionar reset en el ESP32 a media prueba | Caída, reconexión y tiempo sin servicio |
| `ESP32 apagado` | Desconectar la alimentación 10 s y volver a conectar | Igual |
| `cámara desconectada` | Desconectar la cámara USB 5 s y volver a conectarla | STOP al robot, recuperación de la cámara |
| `canal simulado` | Webots con **Simular canal BLE** activado | Reintentos y NACK con 3 % de pérdidas y 2 % de tramas dañadas |

**Tabla de resultados** (copiar de `resumen.md`)

| Condición | Cambios de postura | Enviados | ACK | Éxito | Intentos prom. | Ciclo prom. (ms) | Ciclo p95 (ms) | Caídas | Recuperación prom. (s) | Observaciones |
|---|---|---|---|---|---|---|---|---|---|---|
| base | | | | | | | | | | |
| 2 personas | | | | | | | | | | |
| 3 personas | | | | | | | | | | |
| cambios rápidos | | | | | | | | | | |
| luz baja | | | | | | | | | | |
| contraluz | | | | | | | | | | |
| luz cambiante | | | | | | | | | | |
| distancia | | | | | | | | | | |
| ESP32 reinicio | | | | | | | | | | |
| ESP32 apagado | | | | | | | | | | |
| cámara desconectada | | | | | | | | | | |
| canal simulado | | | | | | | | | | |

---

## 5. Errores y cómo se manejan

| # | Error | Cuándo pasa | Cómo se detecta | Qué hace el sistema |
|---|---|---|---|---|
| E1 | Cámara no disponible al iniciar | Cámara desconectada o usada por otra app | No abre o no da imagen | Aviso en el área de video; reintenta cada 2 s; DETENER cancela. La app no se cierra |
| E2 | Cámara perdida durante la ejecución | Se desconecta el cable USB | 5 lecturas fallidas seguidas | Manda STOP al robot (estado seguro), libera la cámara y la reabre cada 2 s. Registra el tiempo sin servicio |
| E3 | Error al procesar un frame | Frame dañado, fallo de MediaPipe | Excepción en el procesamiento | Se descarta el frame y se sigue. Con 30 seguidos se detiene la detección |
| E4 | ESP32 no encontrado | Apagado o fuera de alcance | La búsqueda BLE (8 s) no lo encuentra | Reintenta solo con esperas de 1, 2, 4, 8 y 10 s. El botón muestra *Cancelar* |
| E5 | Desconexión BLE | Reset del ESP32, sin alimentación, distancia | Aviso de desconexión de `bleak` | Registra la caída y reconecta solo. Al volver, reenvía el modo |
| E6 | Conexión abierta pero sin respuesta | ESP32 colgado, interferencia fuerte | 3 s sin recibir nada (latido PING cada 1 s) | Cierra la conexión y reconecta |
| E7 | Trama o ACK perdido | Interferencia | Sin ACK en 300 ms | Reintenta con el mismo SEQ, hasta 3 veces |
| E8 | Trama dañada | Ruido | El ESP32 revisa el CRC y responde NACK `ERR_CRC` | La PC reintenta |
| E9 | Comando repetido por un reintento | Se perdió el ACK | El ESP32 ve el mismo TYPE y SEQ en menos de 1 s | No lo ejecuta dos veces; solo reenvía el ACK |
| E10 | Demasiados comandos | Cambios de postura muy rápidos | La cola (20) está llena | Se descarta el comando y se registra |
| E11 | Comando sin conexión | Postura detectada mientras se reconecta | Enlace no conectado | No se envía y se registra como "Sin conexión" |
| E12 | La PC deja de mandar | App cerrada o colgada | El ESP32 pasa 3 s sin tramas | El ESP32 entra a estado seguro y regresa al centro |
| E13 | Error inesperado en la GUI | Fallo de programación | `sys.excepthook` | Se registra en la bitácora y en `eventos.csv`; la app sigue abierta |

**Errores encontrados en las pruebas** (llenar con lo que salga en `eventos.csv` y en las observaciones)

| Fecha | Condición | Qué pasó | Error (E#) | Cómo se recuperó | Tiempo sin servicio (s) |
|---|---|---|---|---|---|
| | | | | | |

---

## 6. Prueba rápida sin robot

Sirve para revisar la reconexión antes de ir al laboratorio.

1. Abre el mundo de Webots y conecta **Webots** en la GUI.
2. Detén la simulación: la GUI muestra *Reconectando*.
3. Vuelve a correrla: se reconecta sola y en la bitácora sale `Reconectado tras … s`.
4. Activa **Simular canal BLE** y haz posturas: en `comandos.csv` se ven intentos de 2 o 3 y NACK por CRC, y aun así casi todos los comandos terminan con ACK.
