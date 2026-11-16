# Resumen de la sesión

- Inicio: 2026-11-06T13:33:54
- Duración: 250 s

## Comandos de postura por condición

| Condición | Destino | Enviados | ACK | Éxito | Intentos prom. | RTT prom. (ms) | Ciclo prom. (ms) | Ciclo p95 (ms) | Ciclo máx. (ms) |
|---|---|---|---|---|---|---|---|---|---|
| S1 ciclo 5 posturas | Webots | 100 | 100 | 100.0 % | 1.00 | 9.2 | 10.0 | 14.5 | 17.0 |
| S2 canal BLE simulado | Webots | 300 | 295 | 98.3 % | 1.12 | 69.9 | 104.7 | 374.6 | 672.4 |
| S3 cambios rapidos | Webots | 299 | 298 | 99.7 % | 1.07 | 70.6 | 315.7 | 899.0 | 1226.0 |
| S4 tracking 20 Hz + posturas | Webots | 29 | 29 | 100.0 % | 1.03 | 69.0 | 79.9 | 90.8 | 364.2 |
| S5 simulacion detenida | Webots | 5 | 5 | 100.0 % | 1.00 | 6.9 | 7.4 | 15.6 | 15.6 |
| S6 robot sin respuesta | Webots | 5 | 5 | 100.0 % | 1.00 | 24.9 | 25.4 | 29.0 | 29.0 |

## Posturas detectadas por condición

| Condición | Cambios | INICIO | RECARGAR | ESCUDO | ATAQUE | FIN |
|---|---|---|---|---|---|---|
| S1 ciclo 5 posturas | 0 | 0 | 0 | 0 | 0 | 0 |
| S2 canal BLE simulado | 0 | 0 | 0 | 0 | 0 | 0 |
| S3 cambios rapidos | 0 | 0 | 0 | 0 | 0 | 0 |
| S4 tracking 20 Hz + posturas | 0 | 0 | 0 | 0 | 0 | 0 |
| S5 simulacion detenida | 0 | 0 | 0 | 0 | 0 | 0 |
| S6 robot sin respuesta | 0 | 0 | 0 | 0 | 0 | 0 |

## Comandos fallidos

| Condición | Destino | Causa | Veces |
|---|---|---|---|
| S2 canal BLE simulado | Webots | NACK: Longitud inválida | 5 |
| S3 cambios rapidos | Webots | NACK: Longitud inválida | 1 |

## Eventos

| Evento | Veces |
|---|---|
| Webots:conectado | 1 |
| Webots:perdido | 10 |
| Webots:reconectado | 10 |
| Webots:reintento | 25 |
| gui:etiqueta | 7 |

## Recuperación ante fallas

| Origen | Recuperaciones | Sin servicio prom. (s) | Máx. (s) |
|---|---|---|---|
| Webots | 10 | 4.6 | 8.3 |

## Contadores de los enlaces

| Enlace | caidas | latidos | nacks | reconexiones | reintentos_ack | tramas_track |
|---|---|---|---|---|---|---|
| Webots | 10 | 47 | 9 | 10 | 55 | 892 |
