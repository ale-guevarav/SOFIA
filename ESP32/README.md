# SOFIA - Firmware del ESP32 maestro

Firmware que recibe por **Bluetooth Low Energy (BLE)** los comandos que envía el sistema de visión (PC) y mueve **las 16 unidades del módulo SOFIA (32 servos en dos PCA9685)** según la postura detectada. Por ahora las 16 unidades hacen el mismo movimiento.

La estructura de los mensajes está definida en el estándar de comunicación: [`Vision/docs/PROTOCOLO_COMUNICACION.md`](../Vision/docs/PROTOCOLO_COMUNICACION.md).

```text
ESP32/
└── sofia_maestro/
    ├── sofia_maestro.ino   ← BLE + protocolo (recibe, valida y confirma tramas)
    └── movimiento.h        ← servos, 2 PCA9685 y patrones de movimiento
```

---

## ¿Qué hace?

| Comando que llega de la PC | Qué hacen las 16 unidades |
|---|---|
| POSE 1 · INICIO | Dibujan un **círculo** por turnos (tanda de ~4.0 s) |
| POSE 2 · RECARGAR | Dibujan un **cuadrado** por turnos (~5.2 s) |
| POSE 3 · ESCUDO | Dibujan una **X** por turnos (~5.2 s) |
| POSE 4 · ATAQUE | **Línea arriba-abajo** 2 veces, por turnos (~3.7 s) |
| POSE 5 · FIN | **Zigzag** de izquierda a derecha, por turnos (~3.7 s) |
| TRACK (solo en modo TRACKING) | **Apunta hacia la mano** |
| STOP | Regresa al centro de inmediato |
| PING | Solo responde ACK (comando de prueba) |

- **Por turnos:** las unidades entran a una cola y dibujan la figura **3 a la vez, desfasadas** (una casi acabando, otra a la mitad, otra empezando); la que termina regresa al centro mientras entra la siguiente. Nunca se mueven los 32 servos juntos.
- Todas las figuras miden ±20° desde el centro y se recorren a 240 °/s (~0.6–0.9 s por unidad). Son 20° y no más porque, al moverse desfasadas, dos vecinas pueden inclinarse una hacia la otra: con 30 mm entre aristas, a ±20° quedan ~6 mm entre placas y a ±30° se tocan.
- Al terminar, cada unidad **regresa al centro**.
- Una postura nueva vacía la cola: las que se movían regresan al centro y empieza la tanda nueva.
- En TRACKING las 16 apuntan juntas a la mano (es en tiempo real).
- Se ajusta al inicio de `movimiento.h`: `SIMULTANEAS` (cuántas a la vez), `ORDEN_UNIDADES` (orden de la cola), `REPETICIONES` (veces que se repite cada figura) y `VEL_PATRON`.
- Si se pierde la conexión o pasan 3 s sin mensajes, las unidades van al centro (estado seguro).

---

## Hardware

Igual que las pruebas de mecatrónica (`Prueba_Servos` y `SG90_WindowVelocity_PCA`):

| Elemento | Valor |
|---|---|
| Microcontrolador | ESP32-C3 |
| Drivers PWM | 2 × PCA9685 en el mismo bus I2C, 50 Hz; se detectan solas al arrancar (normalmente `0x40` y `0x41`) |
| I2C | SDA = GPIO 0, SCL = GPIO 1, 400 kHz |
| OE de los PCA9685 | GPIO 5 (LOW = habilitado), compartido |
| Unidades 1–8 | PCA de dirección menor |
| Unidades 9–16 | PCA de dirección mayor |
| Canales en cada placa | Por pares: 0 = X y 1 = Y de su primera unidad, 2 = X y 3 = Y de la segunda, … 14 = X y 15 = Y de la octava |
| Calibración | −60° → 385 cuentas, +60° → 225 cuentas (igual para todos los servos) |

Todo esto se cambia al inicio de `movimiento.h`. Si un eje se mueve al revés en todas las unidades, pon `INVERTIR_X` o `INVERTIR_Y` en `true`. Si una sola unidad no queda plana en el centro, corrígela en `AJUSTE_X` / `AJUSTE_Y` (grados, una casilla por unidad).

La segunda placa necesita **otra dirección**: puentea el jumper `A0` (queda en `0x41`). Si las dos se quedan en `0x40`, el Monitor Serie solo reporta una placa y se mueven 8 unidades.

> **Alimentación:** 32 servos moviéndose juntos piden varios amperes. Aliméntalos por el borne `V+` de los PCA9685 con una fuente aparte de 5–6 V, de al menos 8–10 A, y une las tierras con la del ESP32. Nunca los alimentes desde el ESP32. Al arrancar, el firmware centra las unidades de una en una para no pedir toda la corriente de golpe.

> **Si usan un ESP32-S3:** el Bluetooth funciona igual, pero hay que cambiar `SDA_PIN`, `SCL_PIN` y `OE_PIN`. En el S3 el GPIO 0 se usa al arrancar y no conviene usarlo para I2C.

---

## Cómo cargarlo (Arduino IDE)

1. **Placa:** en *Gestor de placas* instala **esp32** (Espressif).
2. **Librería:** en *Gestor de librerías* instala **Adafruit PWM Servo Driver Library**.
3. Abre `sofia_maestro/sofia_maestro.ino` (`movimiento.h` aparece como otra pestaña).
4. En *Herramientas*:
   - Placa: **ESP32C3 Dev Module** (o la de su tarjeta)
   - **USB CDC On Boot: Enabled** (si no, el Monitor Serie no muestra nada)
5. **Subir** y abrir el Monitor Serie a **115200**. Debe decir:
   ```text
   === SOFIA ESP32 MAESTRO ===
   PCA9685 en 0x40 -> unidades 1-8
   PCA9685 en 0x41 -> unidades 9-16
   Servos listos: 16 unidades en el centro.
   Anunciando como 'SOFIA-ESP32'. Esperando conexión...
   ```

---

## Cómo probarlo

### Sin la PC (solo servos)

En el Monitor Serie, con *"Sin ajuste de línea"*, escribe:

| Tecla | Acción |
|---|---|
| `1` – `5` | Dibuja la figura de esa postura |
| `0` | Regresa al centro |
| `u` | Prueba de cableado: deja moverse **solo una unidad** (cada `u` pasa a la siguiente, del 1 al 16, y al final vuelven todas). El Monitor Serie dice su placa y canales; con `1`–`5` esa unidad sola dibuja la figura |

### Con la PC (comunicación)

Dentro de `Vision/`, con el entorno virtual activo:

```powershell
python ble_test.py
```

Envía PING, POSE = ESCUDO, un TRACK y un PING con CRC dañado. Resultado esperado:

```text
PING confirmado:        OK
POSE confirmada:        OK
Error de CRC detectado: OK
```

En el Monitor Serie aparece cada comando y las unidades dibujan la X de ESCUDO.

También se puede usar la GUI (`python gui_app.py`): **Conectar → Enviar PING → Iniciar**, y hacer posturas frente a la cámara.

---

## Cómo está hecho

### `sofia_maestro.ino`: comunicación

1. El ESP32 se anuncia por BLE como `SOFIA-ESP32` con el servicio *Nordic UART*.
2. Cuando la PC escribe una trama, el callback de BLE **solo la copia a una cola** (FreeRTOS); el trabajo se hace en `loop()`.
3. `handleFrame()` valida en orden: longitud → byte de inicio (`0xA5`) → LEN → **CRC-8** → tipo → datos.
4. Si algo falla responde **NACK** con el código de error; si es válida, ejecuta la acción y responde **ACK** (excepto TRACK, que no lleva ACK).
5. Si llega el mismo comando repetido (mismo tipo y número de secuencia en menos de 1 s), **no lo vuelve a ejecutar** pero sí manda el ACK: así un reintento de la PC no mueve la unidad dos veces.

### `movimiento.h`: servos (16 unidades)

1. Cada figura es **una sola lista de puntos** (x, y) compartida por las 16 unidades; cada unidad solo guarda su posición, en qué punto va y su fase (quieta, figura, regreso, mano). Todo el movimiento ocupa ~1 KB de RAM.
2. Al llegar una postura se arma la ruta y una **cola** con las unidades en `ORDEN_UNIDADES`. Cada 20 ms, `actualizarMovimiento()` arranca la siguiente unidad si hay menos de `SIMULTANEAS` dibujando y ya pasó *duración de la figura / SIMULTANEAS* desde la anterior: eso las deja desfasadas.
3. Cada unidad avanza por la ruta a **velocidad constante** sin frenar en los puntos y, al acabar, regresa al centro.
4. **Solo viajan por I2C las unidades que se movieron** (más de 0.1°): sus dos canales van en una transacción de 9 bytes, ~3 por ciclo. Las quietas no reciben nada; el PCA9685 las mantiene en su posición.
5. En modo TRACKING, el objetivo es la posición de la mano (x, y normalizadas × 45°) y las 16 unidades la siguen con un límite de 300 °/s.
6. Si el Arduino IDE marca *Sketch too big*, es por la librería de Bluetooth, no por el movimiento: elige *Herramientas → Partition Scheme → Huge APP (3MB No OTA)*.
