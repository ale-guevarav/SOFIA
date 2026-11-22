/*
 * =============================================================
 *  SOFIA - ESP32 MAESTRO (BLE + Modbus RTU master por RS485)
 *  Recibe comandos de la PC (visión) por BLE, mueve sus propias
 *  16 unidades (2 PCA9685) y reenvía cada comando a los ESP32
 *  esclavos por RS485 / Modbus RTU.
 * =============================================================
 *
 *  Protocolo con la PC (BLE) -> sin cambios:
 *    +------+------+------+------+-----------------+------+
 *    | SOF  | TYPE | SEQ  | LEN  | PAYLOAD (0-14)  | CRC8 |
 *    | 0xA5 | 1 B  | 1 B  | 1 B  | LEN bytes       | 1 B  |
 *    +------+------+------+------+-----------------+------+
 *
 *  Hacia los esclavos (Modbus RTU, holding registers):
 *    0 POSE   1 MODE   2 STOP   3..7 TRACK(mano,x,y,mag,ang)
 *    8 HEARTBEAT (cada 1 s si no hay otro tráfico)
 *
 *  LIBRERÍAS:
 *    - "modbus-esp8266" (Emelianov)
 *    - "Adafruit PWM Servo Driver Library"
 *
 *  PRUEBA SIN PC (Monitor Serie, 115200, "Sin ajuste de línea"):
 *    1-5 patrón, 0 centro, u/e/p/s/+/- pruebas de movimiento.
 * =============================================================
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ModbusRTU.h>

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

#define MODBUS_BAUD      115200
#define MODBUS_CONFIG    SERIAL_8N1

#define RS485_RX_PIN     4        // <- RO   (ajusta a tu placa)
#define RS485_TX_PIN     5        // -> DI
#define RS485_DE_RE_PIN  6        // DE + RE unidos (-1 si es automático)

// Esclavos: pon aquí los ID de cada uno (deben coincidir con SLAVE_ID)
const uint8_t SLAVE_IDS[] = {1};
#define NUM_SLAVES  (sizeof(SLAVE_IDS) / sizeof(SLAVE_IDS[0]))

// 1 = una sola escritura a ID 0 (broadcast) que oyen todos los esclavos
// 0 = una escritura por esclavo (con ID propio)
#define USE_BROADCAST    0

#define MB_TIMEOUT_MS    100      // máx. espera por transacción
#define MB_BROADCAST_GAP 20       // pausa tras un broadcast (no hay respuesta)
#define HEARTBEAT_MS     1000

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

// Tipos PC -> ESP32
#define TYPE_POSE     0x00
#define TYPE_TRACK    0x01
#define TYPE_PING     0x02
#define TYPE_MODE     0x03
#define TYPE_STOP     0x04

// Tipos ESP32 -> PC
#define TYPE_ACK      0x80
#define TYPE_NACK     0x81

// Códigos de error
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

void enterSafeState(const char* reason);

// =============================================
// MODBUS MASTER
// Cola propia: Modbus RTU solo atiende una
// transacción a la vez.
//  - Comandos (POSE/MODE/STOP): FIFO, no se pierden.
//  - TRACK: un solo hueco, siempre el más reciente.
//  - HEARTBEAT: solo si no hay nada más que mandar.
// =============================================

ModbusRTU mb;

struct Job {
  uint16_t reg;
  uint8_t count;
  uint16_t val[5];
};

#define FIFO_SIZE 8
Job fifo[FIFO_SIZE];
uint8_t fifoHead = 0, fifoTail = 0;

Job trackJob;
bool trackPending = false;

Job curJob;
bool curActive = false;
uint8_t targetIdx = 0;

volatile bool mbBusy = false;
uint32_t mbBusySince = 0;
uint32_t lastMbSendMs = 0;
uint16_t heartbeatCounter = 0;

#if USE_BROADCAST
  #define TARGET_COUNT 1
#else
  #define TARGET_COUNT NUM_SLAVES
#endif

// Termina una transacción (con o sin error)
bool onModbusDone(Modbus::ResultCode event, uint16_t transactionId, void* data) {
  mbBusy = false;
  return true;
}

void fifoPush(uint16_t reg, uint16_t value) {
  uint8_t next = (fifoHead + 1) % FIFO_SIZE;
  if (next == fifoTail) {
    Serial.println("[MODBUS] Cola llena, comando descartado");
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

void modbusPump() {
  mb.task();

  // Libera la línea si la transacción no terminó
  uint32_t timeout = USE_BROADCAST ? MB_BROADCAST_GAP : MB_TIMEOUT_MS;
  if (mbBusy && millis() - mbBusySince > timeout) {
    mbBusy = false;
  }
  if (mbBusy) return;

  // Elegir el siguiente trabajo
  if (!curActive) {
    if (fifoTail != fifoHead) {
      curJob = fifo[fifoTail];
      fifoTail = (fifoTail + 1) % FIFO_SIZE;
    } else if (trackPending) {
      curJob = trackJob;
      trackPending = false;
    } else if (millis() - lastMbSendMs >= HEARTBEAT_MS) {
      curJob.reg = HREG_HEARTBEAT;
      curJob.count = 1;
      curJob.val[0] = ++heartbeatCounter;
    } else {
      return;
    }
    curActive = true;
    targetIdx = 0;
  }

  // Enviar al siguiente esclavo del trabajo actual
#if USE_BROADCAST
  uint8_t id = 0;
#else
  uint8_t id = SLAVE_IDS[targetIdx];
#endif

  uint16_t t;
  if (curJob.count == 1) {
    t = mb.writeHreg(id, curJob.reg, curJob.val[0], onModbusDone);
  } else {
    t = mb.writeHreg(id, curJob.reg, curJob.val, curJob.count, onModbusDone);
  }
  if (!t) return;   // la librería no pudo aceptarla: se reintenta

  mbBusy = true;
  mbBusySince = millis();
  lastMbSendMs = millis();

  if (++targetIdx >= TARGET_COUNT) {
    curActive = false;
  }
}

// =============================================
// CRC-8 (polinomio 0x07, init 0x00)
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
// INTERPRETAR UNA TRAMA
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
  Serial.println("\n=== SOFIA ESP32 MAESTRO (BLE + Modbus) ===");

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
  // RS485 / MODBUS MASTER
  // -----------------------------
  Serial1.begin(MODBUS_BAUD, MODBUS_CONFIG, RS485_RX_PIN, RS485_TX_PIN);
  mb.begin(&Serial1, RS485_DE_RE_PIN);
  mb.master();
  Serial.printf("Modbus master listo: %u esclavo(s)%s\n",
                (unsigned)NUM_SLAVES, USE_BROADCAST ? " (broadcast)" : "");

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
