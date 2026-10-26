"""
CÁMARA DE LA SIMULACIÓN (WEBOTS) - SOFIA

Hilo que recibe las imágenes de la cámara cenital de Webots
(controlador camara_sim) y se las pasa a la GUI.

Es un canal APARTE del de comandos (otro puerto y otro formato):
si la cámara falla o se apaga, ni la visión ni el enlace con el
robot se enteran.

Formato de cada imagen:

    +--------+-------+-------+----------+------------------------+
    | "SOFC" | ancho | alto  | tamaño N | N bytes BGRA (Webots)  |
    | 4 B    | u16   | u16   | u32      |                        |
    +--------+-------+-------+----------+------------------------+
"""

import socket
import struct
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


SIM_CAMERA_HOST = "127.0.0.1"
SIM_CAMERA_PORT = 5556

HEADER = struct.Struct("<4sHHI")
MAGIC = b"SOFC"


class SimCameraClient(QThread):

    frame_ready = Signal(QImage)

    # "esperando", "recibiendo"
    status = Signal(str)


    def __init__(self, host=SIM_CAMERA_HOST, port=SIM_CAMERA_PORT, parent=None):

        super().__init__(parent)

        self.host = host
        self.port = port

        self._running = True
        self._socket = None


    def stop(self):
        self._running = False

        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


    def run(self):

        self.status.emit("esperando")

        while self._running:

            try:
                self._socket = socket.create_connection((self.host, self.port), timeout=1.0)
                self._socket.settimeout(2.0)
                self.status.emit("recibiendo")

                while self._running:
                    image = self._read_image()
                    self.frame_ready.emit(image)

            except (OSError, ValueError):
                pass

            finally:
                if self._socket is not None:
                    try:
                        self._socket.close()
                    except OSError:
                        pass
                    self._socket = None

            if self._running:
                # Webots todavía no está corriendo: reintentar
                self.status.emit("esperando")
                time.sleep(1.0)


    def _read_exactly(self, size):

        chunks = []

        while size > 0:
            chunk = self._socket.recv(min(size, 65536))
            if not chunk:
                raise OSError("conexión cerrada")
            chunks.append(chunk)
            size -= len(chunk)

        return b"".join(chunks)


    def _read_image(self):

        magic, width, height, size = HEADER.unpack(self._read_exactly(HEADER.size))

        if magic != MAGIC or size != width * height * 4:
            raise ValueError("imagen inválida")

        data = self._read_exactly(size)

        # Webots entrega BGRA: en memoria es el formato ARGB32 de Qt.
        # .copy() para que la QImage tenga sus propios datos.
        return QImage(data, width, height, width * 4, QImage.Format.Format_RGB32).copy()
