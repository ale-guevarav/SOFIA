/*
 * =============================================================
 *  SOFIA - ESP32 MAESTRO
 *  Recibe comandos de la PC (visión) por BLE y mueve
 *  una unidad de 2 servos (2 GDL) según la postura
 * =============================================================
 *
 *  Implementa el Estándar de Comunicación
 *  (ver Vision/docs/PROTOCOLO_COMUNICACION.md):
 *
 *    +------+------+------+------+-----------------+------+
 *    | SOF  | TYPE | SEQ  | LEN  | PAYLOAD (0-14)  | CRC8 |
 *    | 0xA5 | 1 B  | 1 B  | 1 B  | LEN bytes       | 1 B  |
 *    +------+------+------+------+-----------------+------+
 *
 *  - Recibe tramas por BLE (servicio tipo Nordic UART).
 *  - Valida SOF, longitud, CRC, tipo y payload.
 *  - Responde ACK o NACK (con código de error).
 *  - Ignora duplicados (reintentos) para no ejecutar dos veces.
 *  - Si deja de recibir tramas 3 s, entra a estado seguro.
 *
 *  MOVIMIENTO (ver movimiento.h):
 *    POSE 1 INICIO   -> círculo
 *    POSE 2 RECARGAR -> cuadrado
 *    POSE 3 ESCUDO   -> X
 *    POSE 4 ATAQUE   -> línea arriba-abajo
 *    POSE 5 FIN      -> zigzag izquierda a derecha
 *    TRACK (en modo TRACKING) -> apunta hacia la mano
 *    STOP / estado seguro     -> regresa al centro
 *
 *  PRUEBA SIN PC (Monitor Serie, 115200, "Sin ajuste de línea"):
 *    escribir 1-5 para dibujar un patrón, 0 para ir al centro.
 *
 *  ARDUINO IDE:
 *    - Core "esp32" de Espressif (Gestor de placas).
 *    - Librería "Adafruit PWM Servo Driver Library"
 *      (la misma de las pruebas de mecatrónica).
 *    - Placa: "ESP32C3 Dev Module" (o la que usen).
 *    - Herramientas > USB CDC On Boot: "Enabled"
 *      (si no, el Monitor Serie no muestra nada).
 *    - Monitor Serie a 115200 baudios.
 *    - Pines y calibración del PCA9685: movimiento.h
 * =============================================================
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#include "movimiento.h"

// =============================================
// CONFIGURACIÓN BLE
// =============================================

#define DEVICE_NAME   "SOFIA-ESP32"

// Nordic UART Service (NUS)
#define SERVICE_UUID  "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define RX_CHAR_UUID  "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  // La PC escribe aquí
#define TX_CHAR_UUID  "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  // El ESP32 notifica aquí

// =============================================
// PROTOCOLO
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

// Reglas de tiempo
#define LINK_TIMEOUT_MS      3000   // Sin tramas -> estado seguro
#define DUPLICATE_WINDOW_MS  1000   // Ventana para detectar reintentos

const char* POSE_NAMES[] = {"?", "INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"};
const char* MODE_NAMES[] = {"JUEGO", "TEST", "TRACKING"};

// =============================================
// ESTADO
// =============================================

BLECharacteristic* txCharacteristic = nullptr;

volatile bool deviceConnected = false;
bool wasConnected = false;

// Paquete crudo recibido por BLE
struct RxPacket {
  uint8_t length;
  uint8_t data[MAX_FRAME + 1];   // +1 para detectar tramas demasiado largas
};

// Cola entre el callback de BLE y loop()
QueueHandle_t rxQueue;
volatile uint32_t droppedPackets = 0;

uint8_t txSeq = 0;
uint32_t lastRxMs = 0;
bool safeState = true;

// Último comando ejecutado (para detectar duplicados)
uint8_t lastCmdType = 0xFF;
uint8_t lastCmdSeq = 0xFF;
uint32_t lastCmdMs = 0;

// Último estado recibido (para que el resto del robot lo use)
uint8_t currentPose = 0;
uint8_t currentMode = 0;

struct TrackData {
  uint8_t hand;
  int16_t x;        // x normalizada × 1000
  int16_t y;        // y normalizada × 1000
  uint16_t mag;     // magnitud × 1000
  uint16_t angle;   // grados × 10
} currentTrack;

uint32_t lastTrackPrintMs = 0;

void enterSafeState(const char* reason);

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
// ENVÍO DE RESPUESTAS
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
// Aquí se conecta la lógica del robot (motores,
// enviar a los ESP32 esclavos, etc.)
// =============================================

void onPose(uint8_t pose) {
  currentPose = pose;
  Serial.printf("[POSE] %u = %s\n", pose, POSE_NAMES[pose]);

  // Cada postura dibuja su patrón (interrumpe el anterior)
  iniciarPatron(pose);
}

void onTrack(const TrackData& track) {
  currentTrack = track;

  // Se imprime cada 500 ms para no saturar el Monitor Serie
  if (millis() - lastTrackPrintMs >= 500) {
    lastTrackPrintMs = millis();
    Serial.printf("[TRACK] mano=%s x=%+.3f y=%+.3f |v|=%.3f ang=%.1f\n",
                  track.hand == 0 ? "IZQ" : "DER",
                  track.x / 1000.0, track.y / 1000.0,
                  track.mag / 1000.0, track.angle / 10.0);
  }

  // Solo se sigue la mano en modo TRACKING
  if (currentMode == 2) {
    seguirMano(track.x / 1000.0f, track.y / 1000.0f);
  }
}

void onPing() {
  Serial.println("[PING] Comando de prueba recibido");
}

void onMode(uint8_t mode) {
  uint8_t previousMode = currentMode;
  currentMode = mode;
  Serial.printf("[MODE] %s\n", MODE_NAMES[mode]);

  // Al entrar o salir de TRACKING se empieza desde el centro
  if ((mode == 2) != (previousMode == 2)) {
    irAlCentro();
  }
}

void onStop() {
  // STOP interrumpe cualquier patrón de inmediato
  irAlCentro();
  enterSafeState("comando STOP");
}

void enterSafeState(const char* reason) {
  if (!safeState) {
    Serial.printf("[SEGURO] Estado seguro: %s\n", reason);
  }
  safeState = true;
  currentPose = 0;

  // Un patrón en curso termina solo y acaba en el centro;
  // cualquier otro movimiento (ej. seguir la mano) se
  // detiene y la unidad regresa al centro
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

  // Tipo y secuencia (si existen) para reportar errores
  uint8_t type = length > 1 ? d[1] : 0xFF;
  uint8_t seq  = length > 2 ? d[2] : 0xFF;

  // -----------------------------
  // VALIDACIONES
  // -----------------------------

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

  // -----------------------------
  // COMANDOS
  // -----------------------------

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
      // TRACK no lleva ACK (flujo continuo)
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
// (se ejecutan en la tarea de BLE: solo copian
//  los datos a la cola; el trabajo se hace en loop)
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

    // Si llega algo más largo que una trama, se marca con
    // MAX_FRAME + 1 para que handleFrame responda ERR_LENGTH
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
  Serial.println("\n=== SOFIA ESP32 MAESTRO ===");

  // -----------------------------
  // SERVOS (PCA9685)
  // -----------------------------

  if (iniciarServos()) {
    Serial.println("PCA9685 listo. Unidad en el centro.");
  } else {
    // Se sigue sin servos para poder probar la comunicación
    Serial.println("ERROR: PCA9685 NO DETECTADO (la comunicación BLE sigue funcionando)");
  }

  rxQueue = xQueueCreate(16, sizeof(RxPacket));

  BLEDevice::init(DEVICE_NAME);

  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(SERVICE_UUID);

  // TX: el ESP32 notifica ACK / NACK
  txCharacteristic = service->createCharacteristic(
    TX_CHAR_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  txCharacteristic->addDescriptor(new BLE2902());

  // RX: la PC escribe las tramas
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
    BLEDevice::startAdvertising();   // Volver a anunciarse
    Serial.println("[BLE] Anunciando de nuevo...");
  }

  // -----------------------------
  // PROCESAR TRAMAS RECIBIDAS
  // -----------------------------

  RxPacket packet;
  while (xQueueReceive(rxQueue, &packet, 0) == pdTRUE) {
    handleFrame(packet);
  }

  // Paquetes que no cupieron en la cola
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
    } else if (c == '0') {
      Serial.println("[SERIAL] Al centro");
      irAlCentro();
    }
  }

  // -----------------------------
  // MOVIMIENTO (cada 20 ms)
  // -----------------------------

  actualizarMovimiento();

  delay(1);
}
