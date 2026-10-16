"""
PROTOCOLO DE COMUNICACIÓN PC <-> ESP32 MAESTRO - SOFIA

Implementación en Python del Estándar de Comunicación
(ver docs/PROTOCOLO_COMUNICACION.md). El firmware del ESP32
(ESP32/sofia_maestro) implementa exactamente la misma trama.

Estructura de la trama (máx. 19 bytes, cabe en un paquete BLE):

    +------+------+------+------+-----------------+------+
    | SOF  | TYPE | SEQ  | LEN  | PAYLOAD (0-14)  | CRC8 |
    | 0xA5 | 1 B  | 1 B  | 1 B  | LEN bytes       | 1 B  |
    +------+------+------+------+-----------------+------+

    - SOF:  inicio de trama, siempre 0xA5.
    - TYPE: tipo de mensaje (comando o respuesta).
    - SEQ:  número de secuencia 0-255 (lo pone quien envía).
    - LEN:  número de bytes del payload.
    - CRC8: CRC-8 (polinomio 0x07, valor inicial 0x00)
            calculado sobre TYPE, SEQ, LEN y PAYLOAD.

Los enteros de varios bytes van en little-endian.
"""

import struct
from dataclasses import dataclass


# =============================================
# CONSTANTES
# =============================================

SOF = 0xA5

HEADER_SIZE = 4          # SOF + TYPE + SEQ + LEN
MAX_PAYLOAD = 14
MAX_FRAME_SIZE = HEADER_SIZE + MAX_PAYLOAD + 1

# -----------------------------
# BLUETOOTH LOW ENERGY
# -----------------------------

# Se usa el perfil "Nordic UART Service" (NUS): es un estándar
# de facto y permite probar con la app nRF Connect.
DEVICE_NAME = "SOFIA-ESP32"

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # PC escribe aquí
TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # ESP32 notifica aquí


# -----------------------------
# TIPOS DE MENSAJE
# -----------------------------

# PC -> ESP32
TYPE_POSE = 0x00    # Postura detectada (1-5)
TYPE_TRACK = 0x01   # Posición de la mano (x, y, vector)
TYPE_PING = 0x02    # Comando de prueba / latido
TYPE_MODE = 0x03    # Modo activo del sistema de visión
TYPE_STOP = 0x04    # Detener: el robot pasa a estado seguro

# ESP32 -> PC
TYPE_ACK = 0x80     # Confirmación
TYPE_NACK = 0x81    # Rechazo con código de error

TYPE_NAMES = {
    TYPE_POSE: "POSE",
    TYPE_TRACK: "TRACK",
    TYPE_PING: "PING",
    TYPE_MODE: "MODE",
    TYPE_STOP: "STOP",
    TYPE_ACK: "ACK",
    TYPE_NACK: "NACK",
}

# Comandos que exigen ACK. TRACK no lo exige porque
# se envía en flujo continuo (gana el más reciente).
REQUIRES_ACK = {TYPE_POSE, TYPE_PING, TYPE_MODE, TYPE_STOP}


# -----------------------------
# VALORES DE LOS PAYLOADS
# -----------------------------

POSE_IDS = {
    "INICIO": 1,
    "RECARGAR": 2,
    "ESCUDO": 3,
    "ATAQUE": 4,
    "FIN": 5,
}

POSE_NAMES = {value: name for name, value in POSE_IDS.items()}

MODE_IDS = {
    "JUEGO": 0,
    "TEST": 1,
    "TRACKING": 2,
}

HAND_IDS = {
    "IZQUIERDA": 0,
    "DERECHA": 1,
}


# -----------------------------
# CÓDIGOS DE ERROR (NACK)
# -----------------------------

ERR_SOF = 0x01           # Byte de inicio incorrecto
ERR_LENGTH = 0x02        # LEN no coincide o excede el máximo
ERR_CRC = 0x03           # CRC incorrecto
ERR_UNKNOWN_TYPE = 0x04  # Tipo de mensaje desconocido
ERR_PAYLOAD = 0x05       # Payload con tamaño o valores inválidos
ERR_BUSY = 0x06          # ESP32 ocupado (cola llena)

ERROR_NAMES = {
    ERR_SOF: "SOF inválido",
    ERR_LENGTH: "Longitud inválida",
    ERR_CRC: "CRC incorrecto",
    ERR_UNKNOWN_TYPE: "Tipo desconocido",
    ERR_PAYLOAD: "Payload inválido",
    ERR_BUSY: "ESP32 ocupado",
}


# -----------------------------
# REGLAS DE TIEMPO
# -----------------------------

ACK_TIMEOUT_S = 0.30      # Espera máxima de un ACK
MAX_RETRIES = 3           # Reintentos de un comando sin ACK
TRACK_MIN_INTERVAL_S = 0.05   # TRACK a máximo 20 Hz
HEARTBEAT_INTERVAL_S = 1.0    # PING de latido si no hay tráfico


# =============================================
# CRC-8
# =============================================

def crc8(data: bytes) -> int:
    """CRC-8 (polinomio 0x07, init 0x00, sin reflexión)."""

    crc = 0x00

    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF

    return crc


# =============================================
# TRAMA
# =============================================

@dataclass
class Frame:

    type: int
    seq: int
    payload: bytes = b""

    @property
    def name(self):
        return TYPE_NAMES.get(self.type, f"0x{self.type:02X}")

    def __str__(self):
        return f"{self.name} seq={self.seq} payload={self.payload.hex(' ') or '-'}"


class ProtocolError(Exception):

    def __init__(self, code, frame_type=None, seq=None):
        self.code = code
        self.frame_type = frame_type
        self.seq = seq
        super().__init__(ERROR_NAMES.get(code, f"Error 0x{code:02X}"))


def build_frame(frame_type: int, seq: int, payload: bytes = b"") -> bytes:
    """Arma una trama lista para enviarse."""

    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"Payload de {len(payload)} bytes (máx. {MAX_PAYLOAD})")

    body = bytes([frame_type & 0xFF, seq & 0xFF, len(payload)]) + bytes(payload)

    return bytes([SOF]) + body + bytes([crc8(body)])


def parse_frame(data: bytes) -> Frame:
    """
    Valida y decodifica una trama recibida.
    Lanza ProtocolError con el código correspondiente si es inválida.
    """

    data = bytes(data)

    frame_type = data[1] if len(data) > 1 else None
    seq = data[2] if len(data) > 2 else None

    if len(data) < HEADER_SIZE + 1:
        raise ProtocolError(ERR_LENGTH, frame_type, seq)

    if data[0] != SOF:
        raise ProtocolError(ERR_SOF, frame_type, seq)

    length = data[3]

    if length > MAX_PAYLOAD or len(data) != HEADER_SIZE + length + 1:
        raise ProtocolError(ERR_LENGTH, frame_type, seq)

    if crc8(data[1:-1]) != data[-1]:
        raise ProtocolError(ERR_CRC, frame_type, seq)

    return Frame(
        type=frame_type,
        seq=seq,
        payload=data[HEADER_SIZE:-1],
    )


# =============================================
# PAYLOADS PC -> ESP32
# =============================================

def pose_payload(pose_id: int) -> bytes:

    if pose_id not in POSE_NAMES:
        raise ValueError(f"Postura inválida: {pose_id} (debe ser 1-5)")

    return bytes([pose_id])


def track_payload(hand_id, x_norm, y_norm, magnitude_norm, angle_deg) -> bytes:
    """
    Codifica la posición de la mano (9 bytes):

        hand   u8   0 = izquierda, 1 = derecha
        x      i16  x normalizada × 1000  (-1000 a 1000)
        y      i16  y normalizada × 1000  (-1000 a 1000)
        mag    u16  magnitud normalizada × 1000 (0 a 1415)
        angle  u16  ángulo en décimas de grado (0 a 3599)
    """

    def clamp(value, low, high):
        return max(low, min(high, int(round(value))))

    return struct.pack(
        "<BhhHH",
        hand_id,
        clamp(x_norm * 1000, -1000, 1000),
        clamp(y_norm * 1000, -1000, 1000),
        clamp(magnitude_norm * 1000, 0, 1415),
        clamp(angle_deg * 10, 0, 3599),
    )


def decode_track_payload(payload: bytes):

    hand_id, x, y, magnitude, angle = struct.unpack("<BhhHH", payload)

    return {
        "hand": hand_id,
        "x_norm": x / 1000,
        "y_norm": y / 1000,
        "magnitude_norm": magnitude / 1000,
        "angle_deg": angle / 10,
    }


def mode_payload(mode_name: str) -> bytes:
    return bytes([MODE_IDS[mode_name]])


# =============================================
# RESPUESTAS ESP32 -> PC
# =============================================

def decode_ack(frame: Frame):
    """Regresa (tipo_confirmado, seq_confirmada)."""

    if frame.type != TYPE_ACK or len(frame.payload) != 2:
        raise ProtocolError(ERR_PAYLOAD, frame.type, frame.seq)

    return frame.payload[0], frame.payload[1]


def decode_nack(frame: Frame):
    """Regresa (tipo_rechazado, seq_rechazada, codigo_error)."""

    if frame.type != TYPE_NACK or len(frame.payload) != 3:
        raise ProtocolError(ERR_PAYLOAD, frame.type, frame.seq)

    return frame.payload[0], frame.payload[1], frame.payload[2]
