# SOFIA - Firmware del ESP32 maestro

Firmware que recibe por **Bluetooth Low Energy (BLE)** los comandos que envía el sistema de visión (PC) y mueve **una unidad de SOFIA de 2 servos (2 grados de libertad)** según la postura detectada.

La estructura de los mensajes está definida en el estándar de comunicación: [`Vision/docs/PROTOCOLO_COMUNICACION.md`](../Vision/docs/PROTOCOLO_COMUNICACION.md).

```text
ESP32/
└── sofia_maestro/
    ├── sofia_maestro.ino   ← BLE + protocolo (recibe, valida y confirma tramas)
    └── movimiento.h        ← servos, PCA9685 y patrones de movimiento
```

---

## ¿Qué hace?

| Comando que llega de la PC | Qué hace la unidad |
|---|---|
| POSE 1 · INICIO | Dibuja un **círculo** (2 vueltas) |
| POSE 2 · RECARGAR | Dibuja un **cuadrado** (2 vueltas) |
| POSE 3 · ESCUDO | Dibuja una **X** |
| POSE 4 · ATAQUE | **Línea arriba-abajo** (3 veces) |
| POSE 5 · FIN | **Zigzag** de izquierda a derecha |
| TRACK (solo en modo TRACKING) | **Apunta hacia la mano** |
| STOP | Regresa al centro de inmediato |
| PING | Solo responde ACK (comando de prueba) |

- Todas las figuras miden ±35° desde el centro y se recorren a 120 °/s.
- Al terminar, la unidad **siempre regresa al centro**.
- Una postura nueva interrumpe la figura que se esté dibujando.
- Si se pierde la conexión o pasan 3 s sin mensajes, la unidad va al centro (estado seguro).

---

## Hardware

Igual que las pruebas de mecatrónica (`Prueba_Servos` y `SG90_WindowVelocity_PCA`):

| Elemento | Valor |
|---|---|
| Microcontrolador | ESP32-C3 |
| Driver PWM | PCA9685 en `0x40`, 50 Hz |
| I2C | SDA = GPIO 0, SCL = GPIO 1 |
| OE del PCA9685 | GPIO 5 (LOW = habilitado) |
| Servo X (horizontal) | Canal 0 |
| Servo Y (vertical) | Canal 1 |
| Calibración | −60° → 385 cuentas, +60° → 225 cuentas |

Todo esto se cambia al inicio de `movimiento.h`. Si un eje se mueve al revés, pon `INVERTIR_X` o `INVERTIR_Y` en `true`.

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
   PCA9685 listo. Unidad en el centro.
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

En el Monitor Serie aparece cada comando y la unidad dibuja la X de ESCUDO.

También se puede usar la GUI (`python gui_app.py`): **Conectar → Enviar PING → Iniciar**, y hacer posturas frente a la cámara.

---

## Cómo está hecho

### `sofia_maestro.ino`: comunicación

1. El ESP32 se anuncia por BLE como `SOFIA-ESP32` con el servicio *Nordic UART*.
2. Cuando la PC escribe una trama, el callback de BLE **solo la copia a una cola** (FreeRTOS); el trabajo se hace en `loop()`.
3. `handleFrame()` valida en orden: longitud → byte de inicio (`0xA5`) → LEN → **CRC-8** → tipo → datos.
4. Si algo falla responde **NACK** con el código de error; si es válida, ejecuta la acción y responde **ACK** (excepto TRACK, que no lleva ACK).
5. Si llega el mismo comando repetido (mismo tipo y número de secuencia en menos de 1 s), **no lo vuelve a ejecutar** pero sí manda el ACK: así un reintento de la PC no mueve la unidad dos veces.

### `movimiento.h`: servos

1. Cada figura es una **lista de puntos** (x, y) en coordenadas de −1 a 1 que se escala a ±35°.
2. Cada 20 ms, `actualizarMovimiento()` avanza la posición hacia el siguiente punto a **velocidad constante**; al llegar, pasa al siguiente.
3. La posición en grados se convierte a cuentas PWM con la misma calibración lineal de mecatrónica (`theta_a_pwm`) y se envía al PCA9685 solo si cambió más de 0.1°.
4. En modo TRACKING, el objetivo es la posición de la mano (x, y normalizadas × 45°) y la unidad la sigue con un límite de 300 °/s.
