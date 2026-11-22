/*
 * =============================================================
 *  SOFIA - ESP32 ESCLAVO (Modbus RTU sobre RS485)
 *  Recibe comandos del maestro por RS485 y mueve las 16
 *  unidades del módulo (2 PCA9685) usando movimiento.h
 * =============================================================
 *
 *  LIBRERÍA (Gestor de librerías):
 *    "modbus-esp8266" de Alexander Emelianov  (incluye ModbusRTU.h)
 *    "Adafruit PWM Servo Driver Library"
 *
 *  CABLEADO (transceptor MAX3485 / SN65HVD72 a 3.3 V):
 *    ESP32 RX_PIN  <- RO
 *    ESP32 TX_PIN  -> DI
 *    ESP32 DE_RE   -> DE y RE (unidos)
 *    A con A, B con B, GND común.
 *    Resistencia de 120 ohm entre A y B SOLO en los dos extremos del bus.
 *    (Si tu módulo tiene dirección automática, pon DE_RE_PIN en -1.)
 *
 *  MAPA DE REGISTROS
 *  ---------------------------------------------------------
 *  Holding registers (el maestro ESCRIBE, funciones 0x06 / 0x10)
 *    0  POSE         1-5 dibuja el patrón, 0 se ignora
 *    1  MODE         0 JUEGO, 1 TEST, 2 TRACKING
 *    2  STOP         escribir 1 -> al centro + estado seguro
 *    3  TRACK_HAND   0 izq, 1 der
 *    4  TRACK_X      int16, x normalizada * 1000
 *    5  TRACK_Y      int16, y normalizada * 1000
 *    6  TRACK_MAG    uint16, magnitud * 1000
 *    7  TRACK_ANGLE  uint16, grados * 10   (escribir ÚLTIMO)
 *    8  HEARTBEAT    cualquier valor; evita el estado seguro
 *
 *  Input registers (el maestro LEE, función 0x04)
 *    0  ESTADO       0 seguro, 1 reposo, 2 dibujando patrón
 *    1  POSE actual
 *    2  MODE actual
 *    3  SEGUNDOS desde el arranque
 *    4  PCA9685 detectados
 *
 *  TIP: escribe TRACK_HAND..TRACK_ANGLE de una sola vez con la
 *  función 0x10 (4..7 en un frame); el esclavo aplica el
 *  movimiento cuando llega TRACK_ANGLE.
 *
 *  Cualquier escritura válida cuenta como "vida" del enlace.
 * =============================================================
 */

#include <ModbusRTU.h>
#include "movimiento.h"

// =============================================
// CONFIGURACIÓN
// =============================================

#define SLAVE_ID        1        // Cambia por cada esclavo (1-247)
#define MODBUS_BAUD     115200
#define MODBUS_CONFIG   SERIAL_8N1

#define RS485_RX_PIN    4        // <- RO   (ajusta a tu placa)
#define RS485_TX_PIN    5        // -> DI
#define RS485_DE_RE_PIN 6        // DE + RE unidos (-1 si es automático)

#define LINK_TIMEOUT_MS 3000

// Registros
enum HregMap : uint16_t {
  HREG_POSE = 0,
  HREG_MODE,
  HREG_STOP,
  HREG_TRACK_HAND,
  HREG_TRACK_X,
  HREG_TRACK_Y,
  HREG_TRACK_MAG,
  HREG_TRACK_ANGLE,
  HREG_HEARTBEAT,
  HREG_COUNT
};

enum IregMap : uint16_t {
  IREG_ESTADO = 0,
  IREG_POSE,
  IREG_MODE,
  IREG_UPTIME,
  IREG_PCA,
  IREG_COUNT
};

const char* POSE_NAMES[] = {"?", "INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"};
const char* MODE_NAMES[] = {"JUEGO", "TEST", "TRACKING"};

// =============================================
// ESTADO
// =============================================

ModbusRTU mb;

uint32_t lastRxMs = 0;
bool safeState = true;
uint8_t currentPose = 0;
uint8_t currentMode = 0;
bool trackPending = false;

uint32_t lastStatusMs = 0;

// =============================================
// ACCIONES
// =============================================

void enterSafeState(const char* reason) {
  if (!safeState) {
    Serial.printf("[SEGURO] Estado seguro: %s\n", reason);
  }
  safeState = true;
  currentPose = 0;
  trackPending = false;

  // Un patrón en curso termina solo en el centro;
  // cualquier otro movimiento se detiene y va al centro
  if (estado != PATRON) {
    irAlCentro();
  }
}

// Se llama en cada escritura válida: el enlace está vivo
void touchLink() {
  lastRxMs = millis();
  safeState = false;
}

// =============================================
// CALLBACKS DE ESCRITURA MODBUS
// Reciben el valor que escribe el maestro y devuelven
// el valor que se guardará en el registro.
// =============================================

uint16_t cbPose(TRegister* reg, uint16_t val) {
  if (val < 1 || val > 5) return reg->value;   // se rechaza (0 = ninguna)
  touchLink();
  currentPose = val;
  Serial.printf("[POSE] %u = %s\n", val, POSE_NAMES[val]);
  iniciarPatron(val);
  return val;
}

uint16_t cbMode(TRegister* reg, uint16_t val) {
  if (val > 2) return reg->value;
  touchLink();

  uint8_t previousMode = currentMode;
  currentMode = val;
  Serial.printf("[MODE] %s\n", MODE_NAMES[val]);

  // Al entrar o salir de TRACKING se empieza desde el centro
  if ((val == 2) != (previousMode == 2)) {
    irAlCentro();
  }
  return val;
}

uint16_t cbStop(TRegister* reg, uint16_t val) {
  if (val != 1) return 0;
  touchLink();
  Serial.println("[STOP]");
  irAlCentro();
  enterSafeState("comando STOP");
  return 0;   // se auto-limpia para poder repetir el STOP
}

uint16_t cbTrackHand(TRegister* reg, uint16_t val) {
  if (val > 1) return reg->value;
  touchLink();
  return val;
}

uint16_t cbTrackAxis(TRegister* reg, uint16_t val) {
  int16_t v = (int16_t)val;
  if (v < -1000 || v > 1000) return reg->value;
  touchLink();
  return val;
}

uint16_t cbTrackMag(TRegister* reg, uint16_t val) {
  if (val > 1415) return reg->value;
  touchLink();
  return val;
}

// Último registro del bloque TRACK: marca que hay dato nuevo
uint16_t cbTrackAngle(TRegister* reg, uint16_t val) {
  if (val > 3599) return reg->value;
  touchLink();
  trackPending = true;
  return val;
}

uint16_t cbHeartbeat(TRegister* reg, uint16_t val) {
  touchLink();
  return val;
}

// =============================================
// SETUP
// =============================================

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.printf("\n=== SOFIA ESP32 ESCLAVO (Modbus RTU, ID %d) ===\n", SLAVE_ID);

  // -----------------------------
  // SERVOS (2 x PCA9685)
  // -----------------------------
  if (iniciarServos()) {
    Serial.printf("Servos listos: %d unidades en el centro.\n",
                  placasEncontradas * UNIDADES_POR_PLACA);
  } else {
    Serial.println("ERROR: NINGUN PCA9685 DETECTADO (Modbus sigue funcionando)");
  }

  // -----------------------------
  // MODBUS RTU / RS485
  // -----------------------------
  Serial1.begin(MODBUS_BAUD, MODBUS_CONFIG, RS485_RX_PIN, RS485_TX_PIN);

  mb.begin(&Serial1, RS485_DE_RE_PIN);
  mb.slave(SLAVE_ID);

  mb.addHreg(0, 0, HREG_COUNT);
  mb.addIreg(0, 0, IREG_COUNT);

  mb.onSetHreg(HREG_POSE,        cbPose);
  mb.onSetHreg(HREG_MODE,        cbMode);
  mb.onSetHreg(HREG_STOP,        cbStop);
  mb.onSetHreg(HREG_TRACK_HAND,  cbTrackHand);
  mb.onSetHreg(HREG_TRACK_X,     cbTrackAxis);
  mb.onSetHreg(HREG_TRACK_Y,     cbTrackAxis);
  mb.onSetHreg(HREG_TRACK_MAG,   cbTrackMag);
  mb.onSetHreg(HREG_TRACK_ANGLE, cbTrackAngle);
  mb.onSetHreg(HREG_HEARTBEAT,   cbHeartbeat);

  mb.Ireg(IREG_PCA, placasEncontradas);

  Serial.println("Esperando comandos Modbus...");
}

// =============================================
// LOOP
// =============================================

void loop() {

  // Atiende las peticiones Modbus
  mb.task();

  // -----------------------------
  // SEGUIR LA MANO (solo en TRACKING)
  // -----------------------------
  if (trackPending) {
    trackPending = false;
    if (currentMode == 2) {
      float x = (int16_t)mb.Hreg(HREG_TRACK_X) / 1000.0f;
      float y = (int16_t)mb.Hreg(HREG_TRACK_Y) / 1000.0f;
      seguirMano(x, y);
    }
  }

  // -----------------------------
  // VIGILANCIA DEL ENLACE
  // -----------------------------
  if (!safeState && millis() - lastRxMs > LINK_TIMEOUT_MS) {
    enterSafeState("sin tramas por 3 s");
  }

  // -----------------------------
  // PRUEBA DESDE EL MONITOR SERIE
  // -----------------------------
  while (Serial.available()) {
    char c = Serial.read();
    if (c >= '1' && c <= '5') {
      Serial.printf("[SERIAL] Prueba de %s\n", POSE_NAMES[c - '0']);
      iniciarPatron(c - '0');
    } else if (c == '0') {
      Serial.println("[SERIAL] Al centro");
      irAlCentro();
    } else if (c == 'u' || c == 'U') {
      Serial.print("PCA9685 detectados: ");
      Serial.println(placasEncontradas);
      siguienteUnidadPrueba();
    } else if (c == 'e' || c == 'E') {
      empezarPrueba();
    } else if (c == 'p' || c == 'P') {
      pausarPrueba();
    } else if (c == 's' || c == 'S') {
      cambiarSuavizador();
    } else if (c == '+') {
      cambiarEscalaVelocidad(1.25f);
    } else if (c == '-') {
      cambiarEscalaVelocidad(0.8f);
    }
  }

  // -----------------------------
  // MOVIMIENTO (cada 20 ms)
  // -----------------------------
  actualizarMovimiento();

  // -----------------------------
  // ESTADO PARA EL MAESTRO (Input registers)
  // -----------------------------
  if (millis() - lastStatusMs >= 100) {
    lastStatusMs = millis();
    mb.Ireg(IREG_ESTADO, safeState ? 0 : (estado == PATRON ? 2 : 1));
    mb.Ireg(IREG_POSE, currentPose);
    mb.Ireg(IREG_MODE, currentMode);
    mb.Ireg(IREG_UPTIME, (uint16_t)(millis() / 1000));
  }

  delay(1);
}