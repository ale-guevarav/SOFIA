
#include <HardwareSerial.h>
#include "movimiento.h"

// ---- Identidad de este nodo (cámbiala en cada esclavo) ----
#define SLAVE_ID         1

// ---- RS485 ----
#define PIN_RS485_RX     4
#define PIN_RS485_TX     5
#define PIN_DE_RE        6
#define MODBUS_BAUD      115200   // igual que el maestro

#define FRAME_TIMEOUT_MS 20       // silencio que descarta una trama a medias
#define LINK_TIMEOUT_MS  3000

// Registros
#define HREG_POSE        0
#define HREG_MODE        1
#define HREG_STOP        2
#define HREG_TRACK_HAND  3
#define HREG_TRACK_X     4
#define HREG_TRACK_Y     5
#define HREG_TRACK_MAG   6
#define HREG_TRACK_ANGLE 7
#define HREG_HEARTBEAT   8
#define HREG_COUNT       9

// Códigos de excepción Modbus
#define EX_ILLEGAL_FUNCTION 0x01
#define EX_ILLEGAL_ADDRESS  0x02
#define EX_ILLEGAL_VALUE    0x03

const char* POSE_NAMES[] = {"?", "INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"};
const char* MODE_NAMES[] = {"JUEGO", "TEST", "TRACKING"};

// =============================================
// ESTADO
// =============================================

HardwareSerial RS485(1);

uint16_t hregs[HREG_COUNT];

uint8_t rxBuf[32];
uint8_t rxIdx = 0;
uint32_t lastByteMs = 0;

uint32_t lastRxMs = 0;
bool safeState = true;
uint8_t currentPose = 0;
uint8_t currentMode = 0;
bool trackPending = false;
uint32_t lastTrackPrintMs = 0;

// =============================================
// MODBUS RTU (a mano)
// =============================================

// CRC16 Modbus (idéntico al del maestro)
uint16_t crc16Modbus(const uint8_t* buf, uint8_t len) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < len; i++) {
    crc ^= buf[i];
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc & 0x0001) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
  }
  return crc;
}

// ¿Los dos últimos bytes de buf[0..len) son el CRC correcto?
bool crcValid(const uint8_t* buf, uint8_t len) {
  if (len < 4) return false;
  uint16_t crc = crc16Modbus(buf, len - 2);
  return lowByte(crc) == buf[len - 2] && highByte(crc) == buf[len - 1];
}

void rs485Transmit(const uint8_t* buf, uint8_t len) {
  digitalWrite(PIN_DE_RE, HIGH);
  delayMicroseconds(50);
  RS485.write(buf, len);
  RS485.flush();
  delayMicroseconds(50);
  digitalWrite(PIN_DE_RE, LOW);
}

// Confirmación estándar: repite addr, función, registro y valor/cantidad
void sendResponse(const uint8_t* req) {
  uint8_t resp[8];
  memcpy(resp, req, 6);
  uint16_t crc = crc16Modbus(resp, 6);
  resp[6] = lowByte(crc);
  resp[7] = highByte(crc);
  rs485Transmit(resp, 8);
}

void sendException(uint8_t addr, uint8_t fc, uint8_t code) {
  if (addr == 0) return;                 // en broadcast nadie responde
  uint8_t resp[5];
  resp[0] = addr;
  resp[1] = fc | 0x80;
  resp[2] = code;
  uint16_t crc = crc16Modbus(resp, 3);
  resp[3] = lowByte(crc);
  resp[4] = highByte(crc);
  rs485Transmit(resp, 5);
  Serial.printf("[MODBUS] Excepcion 0x%02X (funcion 0x%02X)\n", code, fc);
}

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

// 0 = valor correcto; si no, código de excepción
uint8_t validateReg(uint16_t reg, uint16_t v) {
  switch (reg) {
    case HREG_POSE:        return (v >= 1 && v <= 5) ? 0 : EX_ILLEGAL_VALUE;
    case HREG_MODE:        return (v <= 2) ? 0 : EX_ILLEGAL_VALUE;
    case HREG_STOP:        return (v == 1) ? 0 : EX_ILLEGAL_VALUE;
    case HREG_TRACK_HAND:  return (v <= 1) ? 0 : EX_ILLEGAL_VALUE;
    case HREG_TRACK_X:
    case HREG_TRACK_Y: {
      int16_t s = (int16_t)v;
      return (s >= -1000 && s <= 1000) ? 0 : EX_ILLEGAL_VALUE;
    }
    case HREG_TRACK_MAG:   return (v <= 1415) ? 0 : EX_ILLEGAL_VALUE;
    case HREG_TRACK_ANGLE: return (v <= 3599) ? 0 : EX_ILLEGAL_VALUE;
    case HREG_HEARTBEAT:   return 0;
  }
  return EX_ILLEGAL_ADDRESS;
}

void applyReg(uint16_t reg, uint16_t v) {
  hregs[reg] = v;
  touchLink();

  switch (reg) {
    case HREG_POSE:
      currentPose = v;
      Serial.printf("[POSE] %u = %s\n", v, POSE_NAMES[v]);
      iniciarPatron(v);
      break;

    case HREG_MODE: {
      uint8_t previousMode = currentMode;
      currentMode = v;
      Serial.printf("[MODE] %s\n", MODE_NAMES[v]);
      // Al entrar o salir de TRACKING se empieza desde el centro
      if ((v == 2) != (previousMode == 2)) irAlCentro();
      break;
    }

    case HREG_STOP:
      Serial.println("[STOP]");
      irAlCentro();
      enterSafeState("comando STOP");
      break;

    case HREG_TRACK_ANGLE:
      trackPending = true;      // ya llegaron hand, x, y, mag
      break;
  }
}

// =============================================
// INTERPRETAR UNA TRAMA
// =============================================

void processFrame(const uint8_t* f, uint8_t len) {

  // 1. CRC: si es inválido se descarta en silencio
  if (!crcValid(f, len)) {
    Serial.println("[MODBUS] CRC invalido: trama descartada");
    return;
  }

  // 2. Dirección: si es para otro nodo (o es una respuesta ajena), se ignora
  uint8_t addr = f[0];
  if (addr != SLAVE_ID && addr != 0) return;

  uint8_t fc = f[1];

  // ---------------- 0x06 Write Single Register ----------------
  if (fc == 0x06) {
    uint16_t reg = (f[2] << 8) | f[3];
    uint16_t val = (f[4] << 8) | f[5];

    uint8_t err = validateReg(reg, val);
    if (err) { sendException(addr, fc, err); return; }

    applyReg(reg, val);
    if (addr != 0) sendResponse(f);
    return;
  }

  // ---------------- 0x10 Write Multiple Registers ----------------
  if (fc == 0x10) {
    if (len == 8) return;                 // es una respuesta de otro esclavo

    uint16_t reg = (f[2] << 8) | f[3];
    uint16_t qty = (f[4] << 8) | f[5];
    uint8_t  bc  = f[6];

    if (qty < 1 || qty > HREG_COUNT || bc != qty * 2 || len != 9 + bc) {
      sendException(addr, fc, EX_ILLEGAL_VALUE);
      return;
    }
    if (reg + qty > HREG_COUNT) {
      sendException(addr, fc, EX_ILLEGAL_ADDRESS);
      return;
    }

    // Se valida TODO antes de aplicar algo
    for (uint8_t i = 0; i < qty; i++) {
      uint16_t v = (f[7 + 2 * i] << 8) | f[8 + 2 * i];
      uint8_t err = validateReg(reg + i, v);
      if (err) { sendException(addr, fc, err); return; }
    }
    for (uint8_t i = 0; i < qty; i++) {
      uint16_t v = (f[7 + 2 * i] << 8) | f[8 + 2 * i];
      applyReg(reg + i, v);
    }
    if (addr != 0) sendResponse(f);
    return;
  }

  // ---------------- otra función ----------------
  sendException(addr, fc, EX_ILLEGAL_FUNCTION);
}

// ¿Ya llegó una trama completa? La longitud depende de la función.
// También se reconocen las respuestas de otros esclavos (8 o 5 bytes)
// para no mezclarlas con la siguiente trama del maestro.
bool frameComplete() {
  if (rxIdx < 2) return false;

  switch (rxBuf[1]) {
    case 0x06:
      return rxIdx == 8;

    case 0x10:
      if (rxIdx == 8 && crcValid(rxBuf, 8)) return true;   // respuesta ajena
      return rxIdx >= 7 && rxIdx == 9 + rxBuf[6];

    default:
      // función desconocida o excepción: completa en cuanto el CRC cuadra
      return rxIdx >= 5 && crcValid(rxBuf, rxIdx);
  }
}

void readBus() {
  // Silencio largo en el bus: se descarta cualquier trama a medias
  if (rxIdx > 0 && millis() - lastByteMs > FRAME_TIMEOUT_MS) {
    rxIdx = 0;
  }

  while (RS485.available()) {
    if (rxIdx >= sizeof(rxBuf)) rxIdx = 0;
    rxBuf[rxIdx++] = RS485.read();
    lastByteMs = millis();

    if (frameComplete()) {
      processFrame(rxBuf, rxIdx);
      rxIdx = 0;
    }
  }
}

// =============================================
// SETUP
// =============================================

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.printf("\n=== SOFIA ESP32 ESCLAVO (Modbus RTU, ID 0x%02X) ===\n", SLAVE_ID);

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
  // RS485
  // -----------------------------
  pinMode(PIN_DE_RE, OUTPUT);
  digitalWrite(PIN_DE_RE, LOW);
  RS485.begin(MODBUS_BAUD, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);

  Serial.printf("RS485 a %lu baud. Esperando comandos...\n", (unsigned long)MODBUS_BAUD);
}

// =============================================
// LOOP
// =============================================

void loop() {

  // Atiende el bus
  readBus();

  // -----------------------------
  // SEGUIR LA MANO (solo en TRACKING)
  // -----------------------------
  if (trackPending) {
    trackPending = false;
    if (currentMode == 2) {
      float x = (int16_t)hregs[HREG_TRACK_X] / 1000.0f;
      float y = (int16_t)hregs[HREG_TRACK_Y] / 1000.0f;
      seguirMano(x, y);

      if (millis() - lastTrackPrintMs >= 500) {
        lastTrackPrintMs = millis();
        Serial.printf("[TRACK] x=%+.3f y=%+.3f\n", x, y);
      }
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

  delay(1);
}
