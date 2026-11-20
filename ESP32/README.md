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
| POSE 1 · INICIO | El módulo dibuja **arriba-abajo** por el centro (~2.0 s) |
| POSE 2 · RECARGAR | **Círculo de carga**, como antes: una cabeza gira por el borde en sentido horario y las unidades se inclinan hacia afuera con una cola (2 vueltas, 2.4 s) |
| POSE 3 · ESCUDO | El módulo dibuja un **rombo** (~2.1 s) |
| POSE 4 · ATAQUE | El módulo dibuja una **L** (~1.8 s) |
| POSE 5 · FIN | El módulo dibuja **izquierda-derecha** (despedida, ~3.0 s) |
| TRACK (solo en modo TRACKING) | **Apuntan hacia la mano**, por turnos de 4 |
| STOP | Regresan al centro (por turnos de 4) |
| PING | Solo responde ACK (comando de prueba) |

- **La figura la forma el módulo completo, con unidades fijas:** cada figura tiene un **grupo fijo** de unidades (`GRUPO_ESCUDO`…, las que quedan sobre la figura) y una **esfera virtual** recorre la figura a velocidad constante (`VEL_ESFERA`). Las unidades del grupo **siguen a la esfera como en el tracking**: se inclinan hacia ella (con la esfera encima quedan planas y la siguen cuando pasa), así que el movimiento es continuo.
- Solo se mueven las **3 unidades del grupo más cercanas a la esfera** (`SIMULTANEAS`). El relevo es gradual: la que va a salir se apaga conforme se le acerca la que entra (`RELEVO_MM`).
- **RECARGAR es el círculo de carga de siempre** (la cabeza gira continua por el borde, 1.2 s por vuelta), pero solo se mueven las `SIMULTANEAS` unidades más inclinadas: la cola se acorta a lo que ocupan 3 unidades del borde.
- Unidad 1 = abajo a la izquierda, 16 = arriba a la derecha (visto desde la cámara):

  ```
    13  14  15  16    fila de arriba
  9  10  11  12
    5   6   7   8
  1   2   3   4       fila de abajo
  ```
- Las mismas figuras están en la sim (`Webots/.../tracker_esfera_cpp/patrones.hpp`).
- Todas las inclinaciones miden ±20° como máximo: con 30 mm entre aristas, a ±20° quedan ~6 mm entre placas vecinas y a ±30° se tocan.
- Una postura nueva reemplaza a la anterior: la esfera empieza otra vez desde el principio de la figura.
- **TRACKING por turnos (como el reloj de un CPU):** cada 20 ms solo 4 unidades dan un salto corto hacia la mano (máx. 10°) y ceden el turno a las siguientes 4. Ninguna completa su movimiento de golpe: las 16 avanzan casi juntas (llegan en ~0.3 s), pero nunca arrancan más de 8 servos a la vez, para no subir la corriente. El regreso al centro (STOP, estado seguro, fin del TRACKING) usa los mismos turnos. Se ajusta con `TRACK_POR_TURNO`, `TRACK_SALTO_MAX` y `VEL_TRACK`.
- Se ajusta al inicio de `movimiento.h`: `SIMULTANEAS` (cuántas a la vez, 3), `FIG_*` (camino de la esfera), `GRUPO_*` (unidades que pueden moverse en cada figura), `VEL_ESFERA` (mm/s), `DIST_LLENA` / `RADIO_LLENO` / `RADIO_ESFERA` / `RELEVO_MM` (cómo siguen a la esfera), `suavizador` y `escalaVelocidad`, y `FILA_UNIDAD` / `COLUMNA_UNIDAD` (dónde está cada unidad: fila 0 = abajo, columna 0 = izquierda).
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
| `u` | Prueba de cableado: deja moverse **solo una unidad** (cada `u` pasa a la siguiente, del 1 al 16, y al final vuelven todas). La unidad elegida hace arriba-abajo sola (con cualquier postura, mientras esté elegida); el Monitor Serie dice su placa y canales |
| `s` | Cambia el **suavizador** de las unidades: EMA (como la sim) → sin suavizado → arranca de golpe y frena al llegar → suave (2º orden). Manda una figura después para verlo |
| `+` / `-` | Sube / baja la velocidad de las figuras (×1.25 / ×0.8, de ×0.25 a ×4). Aplica desde la siguiente figura |

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

1. Cada figura es **un camino** (`FIG_*`) y **un grupo fijo de unidades** (`GRUPO_*`). Cada unidad solo guarda su posición, su velocidad y su fase (quieta, figura, regreso, mano). Todo el movimiento ocupa menos de 1 KB de RAM.
2. Cada 20 ms, `posicionEsfera()` calcula dónde va la esfera y `objetivoFigura()` decide, para cada unidad del grupo, si es de las `SIMULTANEAS` más cercanas. Si lo es, se inclina hacia la esfera (como en el tracking); si no, va a 0. RECARGAR usa `objetivoRecarga()`: la cabeza gira por el borde y solo se mueven las 3 más inclinadas.
3. `seguirObjetivo()` la lleva a esa inclinación con el suavizador elegido. Cuando la esfera termina el camino y todas vuelven al centro, la postura termina.
4. **Solo viajan por I2C las unidades que se movieron** (más de 0.1°): sus dos canales van en una transacción de 9 bytes, ~3 por ciclo. Las quietas no reciben nada; el PCA9685 las mantiene en su posición.
5. En modo TRACKING, el objetivo es la posición de la mano (x, y normalizadas × 45°) y las 16 unidades la siguen por turnos de 4, a 120 °/s en promedio.
6. Si el Arduino IDE marca *Sketch too big*, es por la librería de Bluetooth, no por el movimiento: elige *Herramientas → Partition Scheme → Huge APP (3MB No OTA)*.
