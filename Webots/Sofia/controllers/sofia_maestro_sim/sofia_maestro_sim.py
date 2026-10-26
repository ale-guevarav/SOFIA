"""
MAESTRO DE LA SIMULACIÓN - SOFIA (Webots)

Hace en Webots lo mismo que el ESP32 maestro en el robot real:

    GUI (sim_link.py) --TCP :5555--> este controlador --> 16 paneles

    - Recibe las MISMAS tramas del protocolo (protocol.py de Vision):
      SOF | TIPO | SEQ | LEN | PAYLOAD | CRC-8.
    - Valida igual que el firmware y contesta ACK / NACK.
    - No ejecuta dos veces un comando repetido (mismo tipo y SEQ < 1 s).
    - Estado seguro: 3 s sin tramas o desconexión -> todo al centro.

Corre en la ESFERA (DEF ESFERA_TARGET) y la mueve:

    TRACK (modo TRACKING)  la esfera va a la posición de la mano
                           y los paneles la siguen.
    POSE                   cada panel dibuja el patrón de esa postura.
    STOP / estado seguro   esfera al centro, sin patrón.

El customData de la esfera le dice a los paneles qué hacer:

    "M<modo> IDLE"                 en reposo
    "M<modo> TRACK"                siguiendo la mano
    "M<modo> POSE <id> <t0>"       patrón de una postura

Los paneles solo apuntan a la esfera en modo TRACKING (M2).
En JUEGO y TEST la ignoran: se quedan en 0,0 y solo hacen los
patrones de las posturas. Fuera de TRACKING la esfera se esconde
bajo el piso (OCULTAR_ESFERA).

Sin GUI conectada se queda en modo JUEGO: paneles en 0,0.

Por TCP cada trama va dentro de un paquete con 1 byte de longitud
al inicio ([N][trama]), así cada paquete equivale a una escritura BLE.
"""

import importlib.util
import os
import socket
import struct
import sys
import time

from controller import Supervisor


# =============================================
# PROTOCOLO (el mismo archivo que usa la GUI)
# =============================================

def load_protocol():
    """
    Busca Vision/comunicacion/protocol.py subiendo desde esta carpeta
    (el proyecto de Webots vive dentro del repositorio SOFIA).
    Se puede indicar otra ruta con la variable SOFIA_PROTOCOL.
    """

    candidates = []

    if os.environ.get("SOFIA_PROTOCOL"):
        candidates.append(os.environ["SOFIA_PROTOCOL"])

    folder = os.path.dirname(os.path.abspath(__file__))
    for _ in range(7):
        candidates.append(os.path.join(folder, "Vision", "comunicacion", "protocol.py"))
        folder = os.path.dirname(folder)

    for path in candidates:
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("sofia_protocol", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"[MAESTRO] Protocolo: {path}")
            return module

    print("[MAESTRO] ERROR: no se encontró Vision/comunicacion/protocol.py")
    print("          Deja la carpeta Webots dentro del repositorio SOFIA")
    print("          o define la variable SOFIA_PROTOCOL con su ruta.")
    sys.exit(1)


p = load_protocol()


# =============================================
# CONFIGURACIÓN
# =============================================

HOST = "127.0.0.1"
PORT = 5555

SAFE_TIMEOUT_S = 3.0          # sin tramas -> estado seguro
DUPLICATE_WINDOW_S = 1.0      # mismo comando repetido -> no se ejecuta
TRACK_TIMEOUT_S = 1.5         # sin TRACK -> esfera al centro

# Esfera
CENTRO = (0.0, 0.0, 0.25)
RANGO_TRACK = 0.30            # m que recorre la esfera con la mano en el borde (|x| = 1)
SUAVIZADO_ESFERA = 0.25       # 0-1: qué tan rápido alcanza su objetivo

# Si la esfera se mueve al revés que la mano en la cámara cenital,
# cambia el signo aquí
INVERTIR_X = False
INVERTIR_Y = False

# Fuera de TRACKING la esfera no se usa: se esconde bajo el piso
OCULTAR_ESFERA = True
ESCONDIDA = (0.0, 0.0, -0.2)


# =============================================
# MAESTRO
# =============================================

class Maestro:

    def __init__(self):

        self.robot = Supervisor()
        self.time_step = int(self.robot.getBasicTimeStep())

        # La esfera se busca por su DEF (igual que los paneles en C++);
        # getSelf() queda como respaldo
        sphere = self.robot.getFromDef("ESFERA_TARGET") or self.robot.getSelf()
        self.translation = sphere.getField("translation") if sphere else None

        if self.translation is None:
            print("[MAESTRO] ERROR: no se pudo leer 'translation' de la esfera "
                  "(DEF ESFERA_TARGET). La comunicación funciona, pero la "
                  "esfera no se moverá.")

        # Posición actual y objetivo de la esfera
        self.position = list(CENTRO)
        self.target = list(CENTRO)

        self.mode = p.MODE_IDS["JUEGO"]
        self.safe = True
        self.last_rx = 0.0
        self.last_track = 0.0

        self.last_cmd = (None, None, 0.0)   # (tipo, seq, momento)
        self.tx_seq = 0

        # -----------------------------
        # SERVIDOR TCP (no bloqueante)
        # -----------------------------

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((HOST, PORT))
        self.server.listen(1)
        self.server.setblocking(False)

        self.client = None
        self.buffer = b""

        self.command = "IDLE"
        self.set_command("IDLE")
        self.update_sphere_visibility()

        print(f"[MAESTRO] Esperando la GUI en {HOST}:{PORT}...")


    # =============================================
    # BUCLE PRINCIPAL
    # =============================================

    def run(self):

        while self.robot.step(self.time_step) != -1:

            self.accept_client()
            self.receive()
            self.check_timeouts()
            self.move_sphere()

        self.close_client()
        self.server.close()


    # =============================================
    # CONEXIÓN
    # =============================================

    def accept_client(self):

        if self.client is not None:
            return

        try:
            client, address = self.server.accept()
        except BlockingIOError:
            return

        client.setblocking(False)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.client = client
        self.buffer = b""
        self.last_rx = time.monotonic()

        print(f"[MAESTRO] GUI conectada desde {address[0]}:{address[1]}")


    def close_client(self):

        if self.client is None:
            return

        try:
            self.client.close()
        except OSError:
            pass

        self.client = None
        self.buffer = b""


    def receive(self):

        if self.client is None:
            return

        try:
            while True:
                chunk = self.client.recv(4096)

                if not chunk:
                    print("[MAESTRO] GUI desconectada")
                    self.close_client()
                    self.enter_safe_state("desconexión")
                    return

                self.buffer += chunk

        except BlockingIOError:
            pass

        except OSError:
            self.close_client()
            self.enter_safe_state("desconexión")
            return

        # Paquetes completos: [N][N bytes]
        while self.buffer:
            size = self.buffer[0]

            if len(self.buffer) < 1 + size:
                break

            packet = self.buffer[1:1 + size]
            self.buffer = self.buffer[1 + size:]

            self.handle_frame(packet)


    def send_frame(self, frame_type, payload):

        if self.client is None:
            return

        frame = p.build_frame(frame_type, self.tx_seq, payload)
        self.tx_seq = (self.tx_seq + 1) % 256

        try:
            self.client.sendall(struct.pack("B", len(frame)) + frame)
        except OSError:
            pass


    def send_ack(self, frame_type, seq):
        self.send_frame(p.TYPE_ACK, bytes([frame_type, seq]))


    def send_nack(self, frame_type, seq, error):
        self.send_frame(p.TYPE_NACK, bytes([frame_type & 0xFF, seq & 0xFF, error]))
        print(f"[NACK] tipo=0x{frame_type & 0xFF:02X} seq={seq & 0xFF} "
              f"error=0x{error:02X} ({p.ERROR_NAMES.get(error, '?')})")


    # =============================================
    # INTERPRETAR UNA TRAMA (igual que el firmware)
    # =============================================

    def handle_frame(self, data):

        frame_type = data[1] if len(data) > 1 else 0xFF
        seq = data[2] if len(data) > 2 else 0xFF

        try:
            frame = p.parse_frame(data)
        except p.ProtocolError as error:
            self.send_nack(frame_type, seq, error.code)
            return

        # Trama válida: la conexión está viva
        self.last_rx = time.monotonic()
        self.safe = False

        payload = frame.payload

        if frame.type == p.TYPE_POSE:
            if len(payload) != 1 or payload[0] not in p.POSE_NAMES:
                self.send_nack(frame.type, frame.seq, p.ERR_PAYLOAD)
                return
            self.run_once(frame, lambda: self.on_pose(payload[0]))

        elif frame.type == p.TYPE_TRACK:
            # TRACK no lleva ACK (flujo continuo)
            if len(payload) != 9:
                self.send_nack(frame.type, frame.seq, p.ERR_PAYLOAD)
                return

            track = p.decode_track_payload(payload)

            if (track["hand"] > 1 or abs(track["x_norm"]) > 1 or abs(track["y_norm"]) > 1
                    or track["magnitude_norm"] > 1.415 or track["angle_deg"] > 359.9):
                self.send_nack(frame.type, frame.seq, p.ERR_PAYLOAD)
                return

            self.on_track(track)

        elif frame.type == p.TYPE_PING:
            if payload:
                self.send_nack(frame.type, frame.seq, p.ERR_PAYLOAD)
                return
            self.run_once(frame, lambda: None)

        elif frame.type == p.TYPE_MODE:
            if len(payload) != 1 or payload[0] > 2:
                self.send_nack(frame.type, frame.seq, p.ERR_PAYLOAD)
                return
            self.run_once(frame, lambda: self.on_mode(payload[0]))

        elif frame.type == p.TYPE_STOP:
            if payload:
                self.send_nack(frame.type, frame.seq, p.ERR_PAYLOAD)
                return
            self.run_once(frame, self.on_stop)

        else:
            self.send_nack(frame.type, frame.seq, p.ERR_UNKNOWN_TYPE)


    def run_once(self, frame, action):
        """Ejecuta el comando salvo que sea un reintento, y contesta ACK."""

        last_type, last_seq, last_time = self.last_cmd
        now = time.monotonic()

        duplicate = (
            frame.type == last_type
            and frame.seq == last_seq
            and now - last_time < DUPLICATE_WINDOW_S
        )

        if not duplicate:
            action()
            self.last_cmd = (frame.type, frame.seq, now)

        self.send_ack(frame.type, frame.seq)


    # =============================================
    # ACCIONES
    # =============================================

    def set_command(self, text):
        # customData del propio robot (la esfera); los paneles lo leen.
        # Siempre lleva el modo para que sepan si deben seguir la esfera.
        self.command = text
        self.robot.setCustomData(f"M{self.mode} {text}")


    def tracking(self):
        return self.mode == p.MODE_IDS["TRACKING"]


    def update_sphere_visibility(self):
        """En TRACKING la esfera está en el arreglo; si no, escondida."""

        if self.tracking() or not OCULTAR_ESFERA:
            self.position = list(CENTRO)
            self.target = list(CENTRO)
            self.set_sphere(CENTRO)
        else:
            self.position = list(ESCONDIDA)
            self.target = list(ESCONDIDA)
            self.set_sphere(ESCONDIDA)


    def set_sphere(self, position):
        if self.translation is not None:
            self.translation.setSFVec3f([float(v) for v in position])


    def on_pose(self, pose_id):
        print(f"[POSE] {pose_id} = {p.POSE_NAMES[pose_id]}")
        # Los paneles usan el tiempo de la simulación como inicio común
        self.set_command(f"POSE {pose_id} {self.robot.getTime():.3f}")


    def on_track(self, track):

        self.last_track = time.monotonic()

        # Solo se sigue la mano en modo TRACKING
        if not self.tracking():
            return

        x = -track["x_norm"] if INVERTIR_X else track["x_norm"]
        y = -track["y_norm"] if INVERTIR_Y else track["y_norm"]

        # Cámara cenital: derecha de la imagen = -Y del mundo,
        # arriba de la imagen = +X del mundo
        self.target = [
            CENTRO[0] + y * RANGO_TRACK,
            CENTRO[1] - x * RANGO_TRACK,
            CENTRO[2],
        ]
        self.set_command("TRACK")


    def on_mode(self, mode):

        previous = self.mode
        self.mode = mode
        print(f"[MODE] {[k for k, v in p.MODE_IDS.items() if v == mode][0]}")

        # Al entrar o salir de TRACKING se empieza desde el centro
        # (o se esconde la esfera); en cualquier caso los paneles
        # reciben el modo nuevo
        if (mode == p.MODE_IDS["TRACKING"]) != (previous == p.MODE_IDS["TRACKING"]):
            self.set_command("IDLE")
            self.update_sphere_visibility()
        else:
            self.set_command(self.command)


    def on_stop(self):
        self.enter_safe_state("comando STOP")


    def enter_safe_state(self, reason):

        if not self.safe:
            print(f"[SEGURO] Estado seguro: {reason}")

        self.safe = True

        # Sin GUI se regresa a JUEGO: paneles en 0,0
        if reason == "desconexión":
            self.mode = p.MODE_IDS["JUEGO"]

        self.set_command("IDLE")
        self.update_sphere_visibility()


    def check_timeouts(self):

        now = time.monotonic()

        if self.client is not None and not self.safe and now - self.last_rx > SAFE_TIMEOUT_S:
            self.enter_safe_state(f"{SAFE_TIMEOUT_S:.0f} s sin tramas")

        if (self.tracking() and self.last_track
                and now - self.last_track > TRACK_TIMEOUT_S):
            self.last_track = 0.0
            self.target = list(CENTRO)


    def move_sphere(self):

        moved = False

        for i in range(3):
            error = self.target[i] - self.position[i]
            if abs(error) > 1e-4:
                self.position[i] += error * SUAVIZADO_ESFERA
                moved = True

        if moved:
            self.set_sphere(self.position)


if __name__ == "__main__":
    Maestro().run()
