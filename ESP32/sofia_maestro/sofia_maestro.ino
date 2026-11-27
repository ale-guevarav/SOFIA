
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <HardwareSerial.h>

#include "movimiento.h"

// =============================================
// CONFIGURACIÓN BLE
// =============================================

#define DEVICE_NAME   "SOFIA-ESP32"

#define SERVICE_UUID  "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define RX_CHAR_UUID  "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define TX_CHAR_UUID  "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

// =============================================
// CONFIGURACIÓN RS485 / MODBUS
// =============================================

#define PIN_RS485_RX     4        // <- MAX485 RO
#define PIN_RS485_TX     5        // -> MAX485 DI
#define PIN_DE_RE        6        // -> MAX485 DE + RE (HIGH = transmite)

// Debe ser IGUAL en maestro y esclavos. La práctica usaba 9600;
// 115200 hace el TRACK mucho más fluido.
#define MODBUS_BAUD      115200

// Esclavos: ID de cada uno (deben coincidir con SLAVE_ID de cada esclavo)
const uint8_t SLAVE_IDS[] = {1};
#define NUM_SLAVES  (sizeof(SLAVE_IDS) / sizeof(SLAVE_IDS[0]))

// 1 = una sola trama a la dirección 0 (broadcast), la oyen todos y
//     nadie responde. 0 = una trama por esclavo, con confirmación.
#define USE_BROADCAST    0

// Espera máxima por la respuesta (incluye el tiempo en el cable)
#define MB_TIMEOUT_MS    (40UL + (30UL * 11UL * 1000UL) / MODBUS_BAUD)
#define MB_RETRIES       2        // reintentos para POSE/MODE/STOP
#define MB_BROADCAST_GAP 10       // pausa tras una trama broadcast
#define HEARTBEAT_MS     1000

// 1 = imprime cada trama TX/RX en hexadecimal (como en la práctica)
#define DEBUG_MODBUS     0

// Registros (mismo mapa que el esclavo)
#define HREG_POSE        0
#define HREG_MODE        1
#define HREG_STOP        2
#define HREG_TRACK       3        // 3..7
#define HREG_HEARTBEAT   8

// =============================================
// PROTOCOLO BLE
// =============================================

#define SOF           0xA5
#define HEADER_SIZE   4
#define MAX_PAYLOAD   14
#define MAX_FRAME     (HEADER_SIZE + MAX_PAYLOAD + 1)

#define TYPE_POSE     0x00
#define TYPE_TRACK    0x01
#define TYPE_PING     0x02
#define TYPE_MODE     0x03
#define TYPE_STOP     0x04
#define TYPE_ADJUST   0x05   // AJUSTE: nuevo "cero" de una unidad (alineación)

#define TYPE_ACK      0x80
#define TYPE_NACK     0x81

#define ERR_SOF          0x01
#define ERR_LENGTH       0x02
#define ERR_CRC          0x03
#define ERR_UNKNOWN_TYPE 0x04
#define ERR_PAYLOAD      0x05
#define ERR_BUSY         0x06

#define LINK_TIMEOUT_MS      3000
#define DUPLICATE_WINDOW_MS  1000

const char* POSE_NAMES[] = {"?", "INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"};
const char* MODE_NAMES[] = {"JUEGO", "TEST", "TRACKING"};

// =============================================
// ESTADO
// =============================================

BLECharacteristic* txCharacteristic = nullptr;

volatile bool deviceConnected = false;
bool wasConnected = false;

struct RxPacket {
  uint8_t length;
  uint8_t data[MAX_FRAME + 1];
};

QueueHandle_t rxQueue;
volatile uint32_t droppedPackets = 0;

uint8_t txSeq = 0;
uint32_t lastRxMs = 0;
bool safeState = true;

uint8_t lastCmdType = 0xFF;
uint8_t lastCmdSeq = 0xFF;
uint32_t lastCmdMs = 0;

uint8_t currentPose = 0;
uint8_t currentMode = 0;

struct TrackData {
  uint8_t hand;
  int16_t x;
  int16_t y;
  uint16_t mag;
  uint16_t angle;
} currentTrack;

uint32_t lastTrackPrintMs = 0;

// ---- Estado del master Modbus ----

HardwareSerial RS485(1);

// Un trabajo = escribir 'count' registros desde 'reg' (1 -> 0x06, >1 -> 0x10)
struct Job {
  uint16_t reg;
  uint8_t count;
  uint16_t val[5];
};

#define FIFO_SIZE 8
Job fifo[FIFO_SIZE];
uint8_t fifoHead = 0, fifoTail = 0;

Job trackJob;                 // solo el TRACK más reciente
bool trackPending = false;

Job curJob;                   // trabajo en curso
bool curActive = false;
bool curCritical = false;     // POSE/MODE/STOP: se reintenta
uint8_t targetIdx = 0;
uint8_t attempt = 0;

enum MbState : uint8_t { MB_IDLE, MB_WAIT, MB_GAP };
MbState mbState = MB_IDLE;

uint8_t txFrame[24];
uint8_t txLen = 0;
uint8_t rxBuf[8];
uint8_t rxLen = 0;
uint8_t rxExpected = 8;
uint32_t mbSentMs = 0;
uint32_t lastMbSendMs = 0;
uint32_t lastMbErrMs = 0;
uint16_t heartbeatCounter = 0;

#if USE_BROADCAST
  #define TARGET_COUNT 1
#else
  #define TARGET_COUNT NUM_SLAVES
#endif

void enterSafeState(const char* reason);

// =============================================
// CRC-8 (BLE con la PC: polinomio 0x07, init 0x00)
// =============================================

uint8_t crc8(const uint8_t* data, size_t length) {
  uint8_t crc = 0x00;
  for (size_t i = 0; i < length; i++) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

// =============================================
// MODBUS RTU (a mano)
// =============================================

// CRC16 Modbus (polinomio 0xA001, semilla 0xFFFF)
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

#if DEBUG_MODBUS
void printFrame(const char* label, const uint8_t* buf, uint8_t len) {
  Serial.printf("%-6s [", label);
  for (uint8_t i = 0; i < len; i++) {
    Serial.printf("%02X", buf[i]);
    if (i < len - 1) Serial.print(' ');
  }
  Serial.println("]");
}
#endif

void rs485Transmit(const uint8_t* buf, uint8_t len) {
  digitalWrite(PIN_DE_RE, HIGH);
  delayMicroseconds(50);
  RS485.write(buf, len);
  RS485.flush();
  delayMicroseconds(50);
  digitalWrite(PIN_DE_RE, LOW);
}

// 0x06: [addr][06][regH][regL][valH][valL][crcL][crcH]               (8 B)
// 0x10: [addr][10][regH][regL][qtyH][qtyL][bytes][datos...][crcL][crcH]
uint8_t buildFrame(uint8_t* out, uint8_t addr, const Job& job) {
  uint8_t n;
  out[0] = addr;
  out[2] = highByte(job.reg);
  out[3] = lowByte(job.reg);

  if (job.count == 1) {
    out[1] = 0x06;
    out[4] = highByte(job.val[0]);
    out[5] = lowByte(job.val[0]);
    n = 6;
  } else {
    out[1] = 0x10;
    out[4] = 0;
    out[5] = job.count;
    out[6] = job.count * 2;
    n = 7;
    for (uint8_t i = 0; i < job.count; i++) {
      out[n++] = highByte(job.val[i]);
      out[n++] = lowByte(job.val[i]);
    }
  }

  uint16_t crc = crc16Modbus(out, n);
  out[n++] = lowByte(crc);
  out[n++] = highByte(crc);
  return n;
}

void fifoPush(uint16_t reg, uint16_t value) {
  uint8_t next = (fifoHead + 1) % FIFO_SIZE;
  if (next == fifoTail) {
    //Serial.println("[MODBUS] Cola llena, comando descartado");
    return;
  }
  fifo[fifoHead].reg = reg;
  fifo[fifoHead].count = 1;
  fifo[fifoHead].val[0] = value;
  fifoHead = next;
}

void queueTrack(const TrackData& t) {
  trackJob.reg = HREG_TRACK;
  trackJob.count = 5;
  trackJob.val[0] = t.hand;
  trackJob.val[1] = (uint16_t)t.x;
  trackJob.val[2] = (uint16_t)t.y;
  trackJob.val[3] = t.mag;
  trackJob.val[4] = t.angle;
  trackPending = true;
}

// STOP urgente: descarta lo pendiente y manda STOP primero
void queueStop() {
  fifoHead = fifoTail = 0;
  trackPending = false;
  fifoPush(HREG_STOP, 1);
}

// Pasa al siguiente esclavo del trabajo; si era el último, lo termina
void advanceTarget() {
  attempt = 0;
  mbState = MB_IDLE;
  if (++targetIdx >= TARGET_COUNT) {
    curActive = false;
  }
}

void sendCurrent() {
#if USE_BROADCAST
  uint8_t id = 0;
#else
  uint8_t id = SLAVE_IDS[targetIdx];
#endif

  txLen = buildFrame(txFrame, id, curJob);

  while (RS485.available()) RS485.read();   // limpia basura vieja

#if DEBUG_MODBUS
  printFrame("TX ->", txFrame, txLen);
#endif
  rs485Transmit(txFrame, txLen);

  mbSentMs = millis();
  lastMbSendMs = mbSentMs;
  rxLen = 0;
  rxExpected = 8;
  mbState = (id == 0) ? MB_GAP : MB_WAIT;   // broadcast: nadie responde
}

// La transacción falló (timeout, CRC malo, respuesta rara)
void failTransaction(const char* why) {
  if (curCritical && attempt < MB_RETRIES) {
    attempt++;
    mbState = MB_IDLE;          // curActive sigue en true: se reenvía igual
    return;
  }

  if (curCritical || millis() - lastMbErrMs > 2000) {
    lastMbErrMs = millis();
    //Serial.printf("[MODBUS] Fallo con nodo 0x%02X (reg %u): %s\n",
     //             txFrame[0], curJob.reg, why);
  }
  advanceTarget();
}

void finishRx() {
#if DEBUG_MODBUS
  printFrame("RX <-", rxBuf, rxLen);
#endif

  uint16_t crc = crc16Modbus(rxBuf, rxLen - 2);
  bool crcOk = (lowByte(crc) == rxBuf[rxLen - 2]) && (highByte(crc) == rxBuf[rxLen - 1]);

  if (!crcOk)                 { failTransaction("CRC invalido"); return; }
  if (rxBuf[0] != txFrame[0]) { failTransaction("responde otro nodo"); return; }

  // Excepción Modbus: [addr][fc|0x80][codigo][crc]
  if (rxBuf[1] == (txFrame[1] | 0x80)) {
    Serial.printf("[MODBUS] Nodo 0x%02X rechazo reg %u (excepcion 0x%02X)\n",
                  txFrame[0], curJob.reg, rxBuf[2]);
    advanceTarget();          // el nodo entendió: no sirve reintentar
    return;
  }

  // Confirmación: repite addr, función, registro y valor/cantidad
  if (memcmp(rxBuf, txFrame, 6) != 0) {
    failTransaction("confirmacion distinta a lo enviado");
    return;
  }

  advanceTarget();
}

// Se llama en cada vuelta de loop(): nunca bloquea
void modbusPump() {

  // ---- pausa tras un broadcast ----
  if (mbState == MB_GAP) {
    if (millis() - mbSentMs >= MB_BROADCAST_GAP) advanceTarget();
    return;
  }

  // ---- esperando la respuesta del esclavo ----
  if (mbState == MB_WAIT) {
    while (RS485.available() && rxLen < rxExpected) {
      rxBuf[rxLen++] = RS485.read();
      if (rxLen == 2) {
        rxExpected = (rxBuf[1] & 0x80) ? 5 : 8;   // excepción = 5 bytes
      }
    }
    if (rxLen >= 2 && rxLen == rxExpected) {
      finishRx();
    } else if (millis() - mbSentMs > MB_TIMEOUT_MS) {
      failTransaction("timeout");
    }
    return;
  }

  // ---- libre: elegir el siguiente trabajo ----
  if (!curActive) {
    if (fifoTail != fifoHead) {
      curJob = fifo[fifoTail];
      fifoTail = (fifoTail + 1) % FIFO_SIZE;
      curCritical = true;
    } else if (trackPending) {
      curJob = trackJob;
      trackPending = false;
      curCritical = false;
    } else if (millis() - lastMbSendMs >= HEARTBEAT_MS) {
      curJob.reg = HREG_HEARTBEAT;
      curJob.count = 1;
      curJob.val[0] = ++heartbeatCounter;
      curCritical = false;
    } else {
      return;
    }
    curActive = true;
    targetIdx = 0;
    attempt = 0;
  }

  sendCurrent();
}

// =============================================
// ENVÍO DE RESPUESTAS A LA PC (BLE)
// =============================================

void sendFrame(uint8_t type, const uint8_t* payload, uint8_t length) {
  if (!deviceConnected || txCharacteristic == nullptr) return;

  uint8_t frame[MAX_FRAME];
  frame[0] = SOF;
  frame[1] = type;
  frame[2] = txSeq++;
  frame[3] = length;
  memcpy(&frame[HEADER_SIZE], payload, length);
  frame[HEADER_SIZE + length] = crc8(&frame[1], 3 + length);

  txCharacteristic->setValue(frame, HEADER_SIZE + length + 1);
  txCharacteristic->notify();
}

void sendAck(uint8_t type, uint8_t seq) {
  uint8_t payload[2] = {type, seq};
  sendFrame(TYPE_ACK, payload, 2);
}

void sendNack(uint8_t type, uint8_t seq, uint8_t error) {
  uint8_t payload[3] = {type, seq, error};
  sendFrame(TYPE_NACK, payload, 3);
  Serial.printf("[NACK] tipo=0x%02X seq=%u error=0x%02X\n", type, seq, error);
}

// =============================================
// ACCIONES
// Cada acción mueve las unidades de ESTE ESP32
// y además la reenvía a los esclavos por Modbus.
// =============================================

void onPose(uint8_t pose) {
  currentPose = pose;
  Serial.printf("[POSE] %u = %s\n", pose, POSE_NAMES[pose]);

  iniciarPatron(pose);          // local
  fifoPush(HREG_POSE, pose);    // esclavos
}

void onTrack(const TrackData& track) {
  currentTrack = track;

  if (millis() - lastTrackPrintMs >= 500) {
    lastTrackPrintMs = millis();
    Serial.printf("[TRACK] mano=%s x=%+.3f y=%+.3f |v|=%.3f ang=%.1f\n",
                  track.hand == 0 ? "IZQ" : "DER",
                  track.x / 1000.0, track.y / 1000.0,
                  track.mag / 1000.0, track.angle / 10.0);
  }

  // Solo se sigue la mano en modo TRACKING
  if (currentMode == 2) {
    seguirMano(track.x / 1000.0f, track.y / 1000.0f);   // local
    queueTrack(track);                                   // esclavos
  }
}

void onPing() {
  Serial.println("[PING] Comando de prueba recibido");
}

void onMode(uint8_t mode) {
  uint8_t previousMode = currentMode;
  currentMode = mode;
  Serial.printf("[MODE] %s\n", MODE_NAMES[mode]);

  if ((mode == 2) != (previousMode == 2)) {
    irAlCentro();
  }
  fifoPush(HREG_MODE, mode);    // esclavos
}

void onStop() {
  // enterSafeState también manda el STOP a los esclavos
  irAlCentro();
  enterSafeState("comando STOP");
}

// AJUSTE (desde la GUI): nuevo cero de una unidad, medido con la app de
// alineación ("Alinear" / "Tomar ceros", o los ceros guardados que manda
// la PC al conectarse). Solo las unidades de ESTE ESP32
void onAdjust(uint8_t unit, bool sacudir, float ajusteX, float ajusteY) {
  Serial.printf("[AJUSTE] Unidad %u (numero %u de la app): X %+.1f  Y %+.1f%s\n",
                unit + 1, unit, ajusteX, ajusteY, sacudir ? "  (reacomodando)" : "");
  fijarAjuste(unit, ajusteX, ajusteY, sacudir);
}

void enterSafeState(const char* reason) {
  if (!safeState) {
    Serial.printf("[SEGURO] Estado seguro: %s\n", reason);
    queueStop();                // los esclavos también van a seguro
  }
  safeState = true;
  currentPose = 0;

  if (estado != PATRON) {
    irAlCentro();
  }
}

// =============================================
// INTERPRETAR UNA TRAMA BLE
// =============================================

bool isDuplicate(uint8_t type, uint8_t seq) {
  return type == lastCmdType
      && seq == lastCmdSeq
      && (millis() - lastCmdMs) < DUPLICATE_WINDOW_MS;
}

void rememberCommand(uint8_t type, uint8_t seq) {
  lastCmdType = type;
  lastCmdSeq = seq;
  lastCmdMs = millis();
}

void handleFrame(const RxPacket& packet) {
  const uint8_t* d = packet.data;
  uint8_t length = packet.length;

  uint8_t type = length > 1 ? d[1] : 0xFF;
  uint8_t seq  = length > 2 ? d[2] : 0xFF;

  if (length < HEADER_SIZE + 1 || length > MAX_FRAME) {
    sendNack(type, seq, ERR_LENGTH);
    return;
  }

  if (d[0] != SOF) {
    sendNack(type, seq, ERR_SOF);
    return;
  }

  uint8_t payloadLength = d[3];

  if (payloadLength > MAX_PAYLOAD || length != HEADER_SIZE + payloadLength + 1) {
    sendNack(type, seq, ERR_LENGTH);
    return;
  }

  if (crc8(&d[1], 3 + payloadLength) != d[length - 1]) {
    sendNack(type, seq, ERR_CRC);
    return;
  }

  // Trama válida: la conexión está viva
  lastRxMs = millis();
  safeState = false;

  const uint8_t* payload = &d[HEADER_SIZE];

  switch (type) {

    case TYPE_POSE: {
      if (payloadLength != 1 || payload[0] < 1 || payload[0] > 5) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      if (!isDuplicate(type, seq)) {
        onPose(payload[0]);
        rememberCommand(type, seq);
      }
      sendAck(type, seq);
      break;
    }

    case TYPE_TRACK: {
      if (payloadLength != 9) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      TrackData track;
      track.hand  = payload[0];
      track.x     = (int16_t)(payload[1] | (payload[2] << 8));
      track.y     = (int16_t)(payload[3] | (payload[4] << 8));
      track.mag   = (uint16_t)(payload[5] | (payload[6] << 8));
      track.angle = (uint16_t)(payload[7] | (payload[8] << 8));

      if (track.hand > 1 || track.x < -1000 || track.x > 1000 ||
          track.y < -1000 || track.y > 1000 || track.mag > 1415 ||
          track.angle > 3599) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      onTrack(track);
      break;
    }

    case TYPE_PING: {
      if (payloadLength != 0) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      if (!isDuplicate(type, seq)) {
        onPing();
        rememberCommand(type, seq);
      }
      sendAck(type, seq);
      break;
    }

    case TYPE_MODE: {
      if (payloadLength != 1 || payload[0] > 2) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      if (!isDuplicate(type, seq)) {
        onMode(payload[0]);
        rememberCommand(type, seq);
      }
      sendAck(type, seq);
      break;
    }

    case TYPE_STOP: {
      if (payloadLength != 0) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      if (!isDuplicate(type, seq)) {
        onStop();
        rememberCommand(type, seq);
      }
      sendAck(type, seq);
      break;
    }

    case TYPE_ADJUST: {
      // unit u8 · flags u8 (bit 0 = reacomodar) · X i16 · Y i16 (décimas de grado)
      if (payloadLength != 6 || payload[0] >= NUM_UNIDADES) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      int16_t ax = (int16_t)(payload[2] | (payload[3] << 8));
      int16_t ay = (int16_t)(payload[4] | (payload[5] << 8));
      if (ax < -AJUSTE_MAX_DECIMAS || ax > AJUSTE_MAX_DECIMAS ||
          ay < -AJUSTE_MAX_DECIMAS || ay > AJUSTE_MAX_DECIMAS) {
        sendNack(type, seq, ERR_PAYLOAD);
        return;
      }
      if (!isDuplicate(type, seq)) {
        onAdjust(payload[0], payload[1] & 0x01, ax / 10.0f, ay / 10.0f);
        rememberCommand(type, seq);
      }
      sendAck(type, seq);
      break;
    }

    default:
      sendNack(type, seq, ERR_UNKNOWN_TYPE);
      break;
  }
}

// =============================================
// CALLBACKS BLE
// =============================================

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* server) override {
    deviceConnected = true;
  }
  void onDisconnect(BLEServer* server) override {
    deviceConnected = false;
  }
};

class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    RxPacket packet;
    size_t length = characteristic->getLength();

    packet.length = length > MAX_FRAME ? MAX_FRAME + 1 : length;
    memcpy(packet.data, characteristic->getData(),
           length > sizeof(packet.data) ? sizeof(packet.data) : length);

    if (xQueueSend(rxQueue, &packet, 0) != pdTRUE) {
      droppedPackets++;
    }
  }
};

// =============================================
// SETUP
// =============================================

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== SOFIA ESP32 MAESTRO (BLE + Modbus RTU) ===");

  // -----------------------------
  // SERVOS (2 x PCA9685)
  // -----------------------------
  if (iniciarServos()) {
    Serial.printf("Servos listos: %d unidades en el centro.\n",
                  placasEncontradas * UNIDADES_POR_PLACA);
  } else {
    Serial.println("ERROR: NINGUN PCA9685 DETECTADO (la comunicación sigue funcionando)");
  }

  // -----------------------------
  // RS485
  // -----------------------------
  pinMode(PIN_DE_RE, OUTPUT);
  digitalWrite(PIN_DE_RE, LOW);
  RS485.begin(MODBUS_BAUD, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);
  Serial.printf("Modbus RTU master a %lu baud: %u esclavo(s)%s\n",
                (unsigned long)MODBUS_BAUD, (unsigned)NUM_SLAVES,
                USE_BROADCAST ? " (broadcast)" : "");

  // -----------------------------
  // BLE
  // -----------------------------
  rxQueue = xQueueCreate(16, sizeof(RxPacket));

  BLEDevice::init(DEVICE_NAME);

  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(SERVICE_UUID);

  txCharacteristic = service->createCharacteristic(
    TX_CHAR_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  txCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic* rxCharacteristic = service->createCharacteristic(
    RX_CHAR_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
  );
  rxCharacteristic->setCallbacks(new RxCallbacks());

  service->start();
  BLEDevice::startAdvertising();

  Serial.printf("Anunciando como '%s'. Esperando conexión...\n", DEVICE_NAME);
}

// =============================================
// LOOP
// =============================================

void loop() {

  // -----------------------------
  // CONEXIÓN / DESCONEXIÓN
  // -----------------------------
  if (deviceConnected && !wasConnected) {
    wasConnected = true;
    lastRxMs = millis();
    Serial.println("[BLE] PC conectada");
  }

  if (!deviceConnected && wasConnected) {
    wasConnected = false;
    Serial.println("[BLE] PC desconectada");
    enterSafeState("desconexión");
    BLEDevice::startAdvertising();
    Serial.println("[BLE] Anunciando de nuevo...");
  }

  // -----------------------------
  // PROCESAR TRAMAS RECIBIDAS
  // -----------------------------
  RxPacket packet;
  while (xQueueReceive(rxQueue, &packet, 0) == pdTRUE) {
    handleFrame(packet);
  }

  if (droppedPackets > 0) {
    Serial.printf("[AVISO] %u tramas descartadas (cola llena)\n", (unsigned)droppedPackets);
    droppedPackets = 0;
    sendNack(0xFF, 0xFF, ERR_BUSY);
  }

  // -----------------------------
  // VIGILANCIA DEL ENLACE
  // -----------------------------
  if (deviceConnected && !safeState && millis() - lastRxMs > LINK_TIMEOUT_MS) {
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
      fifoPush(HREG_POSE, c - '0');      // también a los esclavos
    } else if (c == '0') {
      Serial.println("[SERIAL] Al centro");
      irAlCentro();
      queueStop();
    } else if (c == 'u' || c == 'U') {
      Serial.println("COMANDO U RECIBIDO");
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
  // MODBUS (reenvío a esclavos + heartbeat)
  // -----------------------------
  modbusPump();

  // -----------------------------
  // MOVIMIENTO LOCAL (cada 20 ms)
  // -----------------------------
  actualizarMovimiento();

  delay(1);
}
