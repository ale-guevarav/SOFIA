# SOFIA - Firmware de los ESP32

El **maestro** recibe por **Bluetooth Low Energy (BLE)** los comandos que envía el sistema de visión (PC) y mueve **las 16 unidades del módulo SOFIA (32 servos en dos PCA9685)** según la postura detectada. Además reenvía los comandos por **RS-485 (Modbus)** a los **esclavos**, que mueven otros módulos con el mismo `movimiento.h`.

La estructura de los mensajes está definida en el estándar de comunicación: [`Vision/docs/PROTOCOLO_COMUNICACION.md`](../Vision/docs/PROTOCOLO_COMUNICACION.md).

```text
ESP32/
├── sofia_maestro/
│   ├── sofia_maestro.ino   ← BLE + protocolo (recibe, valida y confirma tramas) + maestro Modbus
│   └── movimiento.h        ← servos, 2 PCA9685 y patrones de movimiento
├── SOFIA_SLAVE/
│   ├── SOFIA_SLAVE.ino     ← esclavo Modbus (RS-485): recibe POSE / MODE / STOP / TRACK del maestro
│   └── movimiento.h        ← el mismo movimiento que el maestro
└── sofia_desalineo_azar/   ← prueba para el diagnóstico de alineación (ángulos al azar conocidos)
    ├── sofia_desalineo_azar.ino
    └── monitor_muestreo.py ← Monitor Serie que guarda el CSV del muestreo en la PC
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
| POSE 6 · GANA | Vaquerito: el robot ganó. **Zigzag que sube** por todo el módulo (~3.0 s) |
| POSE 7 · PIERDE | Vaquerito: el robot perdió. **Zigzag que cae** y se va cerrando (~4.4 s) |
| TRACK (solo en modo TRACKING) | **Apuntan hacia la mano** (EMA) |
| STOP | Regresan al centro (EMA) |
| AJUSTE (unidad 0–15 + cero X/Y) | **Nuevo cero** de esa unidad, medido con el diagnóstico de alineación (menú **Alineación** de la GUI). Con "reacomodar" hace una sacudida corta (±4°) y se asienta; sin él solo reescribe el PWM. La GUI manda los ceros guardados cada vez que se conecta. Solo las unidades del maestro (no se reenvía a los esclavos); si el ESP32 se reinicia sin PC, usa `AJUSTE_X/Y` |
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
- **EMA en todo:** el tracking, el regreso al centro y el reacomodo de *Alinear* usan el mismo EMA de las figuras (`K_SUAVIZADO`), porque así los servos se mueven mejor (`EMA_EN_TRACKING`, `EMA_EN_REGRESO`, `EMA_EN_ALINEAR` en `movimiento.h`). Con EMA las 16 se mueven a la vez.
- **Turnos (si el ESP32 se reinicia por corriente):** con `EMA_EN_TRACKING` / `EMA_EN_REGRESO` en `false`, el tracking y el regreso al centro van por turnos, como el reloj de un CPU: cada 20 ms solo 4 unidades dan un salto corto (máx. 10°) y ceden el turno, así nunca arrancan más de 8 servos a la vez. Se ajusta con `TRACK_POR_TURNO`, `TRACK_SALTO_MAX` y `VEL_TRACK`.
- **Sentido del tracking:** la imagen de la PC llega en espejo; con la mano arriba-derecha (vista de frente) las placas apuntan arriba-derecha. Si un eje sale al revés, `TRACK_INVERTIR_X` / `TRACK_INVERTIR_Y` (solo cambian el tracking, no las figuras).
- Se ajusta al inicio de `movimiento.h`: `SIMULTANEAS` (cuántas a la vez, 3), `FIG_*` (camino de la esfera), `GRUPO_*` (unidades que pueden moverse en cada figura), `VEL_ESFERA` (mm/s), `DIST_LLENA` / `RADIO_LLENO` / `RADIO_ESFERA` / `RELEVO_MM` (cómo siguen a la esfera), `suavizador` y `escalaVelocidad`, y `FILA_UNIDAD` / `COLUMNA_UNIDAD` (dónde está cada unidad: fila 0 = abajo, columna 0 = izquierda).
- Si se pierde la conexión o pasan 3 s sin mensajes, las unidades van al centro (estado seguro).

---

## Hardware

Igual que las pruebas de mecatrónica (`Prueba_Servos` y `SG90_WindowVelocity_PCA`):

| Elemento | Valor |
|---|---|
| Microcontrolador | ESP32-C3 |
| Drivers PWM | 2 × PCA9685 en el mismo bus I2C, 50 Hz; se detectan solas al arrancar (normalmente `0x40` y `0x41`) |
| I2C | SDA = GPIO 0, SCL = GPIO 1, 100 kHz (`I2C_HZ`) |
| OE de los PCA9685 | GPIO 5 (LOW = habilitado), compartido |
| Unidades 1–8 | PCA de dirección menor |
| Unidades 9–16 | PCA de dirección mayor |
| Canales en cada placa | Por pares: 0 = X y 1 = Y de su primera unidad, 2 = X y 3 = Y de la segunda, … 14 = X y 15 = Y de la octava |
| Calibración | −60° → 385 cuentas, +60° → 225 cuentas (igual para todos los servos) |

Todo esto se cambia al inicio de `movimiento.h`. Si un eje se mueve al revés en todas las unidades, pon `INVERTIR_X` o `INVERTIR_Y` en `true`. Si una unidad no queda plana en el centro, lo normal es corregirla desde la GUI (**Alineación → Tomar ceros / Alinear**): los ceros se guardan en la PC y se mandan al ESP32 cada vez que se conecta. `AJUSTE_X` / `AJUSTE_Y` son los ceros "de fábrica" que usa sin PC.

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
| `1` – `7` | Dibuja la figura de esa postura (`6` GANA, `7` PIERDE) |
| `0` | Regresa al centro |
| `u` | Prueba unidad por unidad: **elige la siguiente unidad** (1, 2… 16 y al final "todas"). El Monitor Serie dice su placa y canales. No la mueve sola: con `e` empieza su prueba. Si ya había una prueba en curso, sigue con la nueva unidad |
| `e` | **Empieza el movimiento de prueba** de la unidad elegida (si no hay ninguna, la 1): arriba, abajo, izquierda, derecha, diagonal ↗ ↙ y diagonal ↖ ↘, a 60 °/s con una pausa en cada punto, en ciclo (~9 s por vuelta). Las demás se quedan al centro |
| `p` | **Pausa** el movimiento de prueba: la unidad regresa al centro |
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

En el Monitor Serie aparece cada comando y las unidades dibujan el rombo de ESCUDO.

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
5. En modo TRACKING, el objetivo es la posición de la mano (x, y normalizadas × 45°) y las 16 unidades la siguen con EMA (o por turnos, ver arriba).
6. Si el Arduino IDE marca *Sketch too big*, es por la librería de Bluetooth, no por el movimiento: elige *Herramientas → Partition Scheme → Huge APP (3MB No OTA)*.

---

## Prueba de ángulos al azar (`sofia_desalineo_azar/`)

Programa aparte (no es el firmware del maestro) para sacar fotos con **ángulos conocidos** y entrenar / validar el diagnóstico de alineación. Mismo hardware que el maestro. Monitor Serie a 115200, *Sin ajuste de línea*:

| Tecla | Acción |
|---|---|
| `d` / `D` | 4 / las 16 unidades a ángulos al azar (±10° por eje); se quedan quietas e imprime la tabla con los ángulos (convención de la app: θ1 + derecha, θ2 + arriba). Avisa "Listo: … FOTO N" |
| `0` | Todas al centro (también cuenta como muestra) |
| `f` | Imprime el CSV de todo el muestreo (hasta 400 muestras, en la RAM del ESP32) |
| `x` / `n` | Borra la última muestra / empieza un muestreo nuevo |

En vez del Monitor Serie del Arduino IDE se puede usar `python monitor_muestreo.py COM5` (necesita `pyserial`): manda las teclas sin Enter, **guarda el CSV solo en la PC** (`muestreos/`) y lo va autoguardando aunque el ESP32 se reinicie. Una foto por muestra, en orden.

