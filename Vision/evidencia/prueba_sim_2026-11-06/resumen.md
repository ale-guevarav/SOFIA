# Resumen de la sesión

- Inicio: 2026-11-06T13:40:30
- Duración: 251 s

## Comandos de postura por condición

| Condición | Destino | Enviados | ACK | Éxito | Intentos prom. | RTT prom. (ms) | Ciclo prom. (ms) | Ciclo p95 (ms) | Ciclo máx. (ms) |
|---|---|---|---|---|---|---|---|---|---|
| S1 ciclo 5 posturas | Webots | 100 | 100 | 100.0 % | 1.00 | 9.1 | 9.7 | 14.4 | 17.5 |
| S2 canal BLE simulado | Webots | 300 | 300 | 100.0 % | 1.14 | 69.5 | 105.3 | 371.3 | 678.0 |
| S3 cambios rapidos | Webots | 300 | 300 | 100.0 % | 1.08 | 70.0 | 318.9 | 831.4 | 1115.7 |
| S4 tracking 20 Hz + posturas | Webots | 29 | 29 | 100.0 % | 1.07 | 71.5 | 92.8 | 375.8 | 386.5 |
| S5 simulacion detenida | Webots | 5 | 5 | 100.0 % | 1.00 | 10.7 | 11.0 | 13.2 | 13.2 |
| S6 robot sin respuesta | Webots | 5 | 5 | 100.0 % | 1.00 | 7.6 | 8.1 | 14.6 | 14.6 |

## Posturas detectadas por condición

| Condición | Cambios | INICIO | RECARGAR | ESCUDO | ATAQUE | FIN |
|---|---|---|---|---|---|---|
| S1 ciclo 5 posturas | 0 | 0 | 0 | 0 | 0 | 0 |
| S2 canal BLE simulado | 0 | 0 | 0 | 0 | 0 | 0 |
| S3 cambios rapidos | 0 | 0 | 0 | 0 | 0 | 0 |
| S4 tracking 20 Hz + posturas | 0 | 0 | 0 | 0 | 0 | 0 |
| S5 simulacion detenida | 0 | 0 | 0 | 0 | 0 | 0 |
| S6 robot sin respuesta | 0 | 0 | 0 | 0 | 0 | 0 |

## Eventos

| Evento | Veces |
|---|---|
| Webots:conectado | 1 |
| Webots:error | 5 |
| Webots:perdido | 10 |
| Webots:reconectado | 10 |
| Webots:reintento | 30 |
| gui:etiqueta | 7 |

## Recuperación ante fallas

| Origen | Recuperaciones | Sin servicio prom. (s) | Máx. (s) |
|---|---|---|---|
| Webots | 10 | 6.1 | 8.3 |

## Contadores de los enlaces

| Enlace | caidas | latidos | nacks | reconexiones | reintentos_ack | tramas_track |
|---|---|---|---|---|---|---|
| Webots | 10 | 40 | 9 | 10 | 84 | 893 |
