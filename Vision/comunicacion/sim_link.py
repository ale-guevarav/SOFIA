"""
ENLACE PC -> SIMULACIÓN DE WEBOTS - SOFIA

Misma lógica que BleLink (ACK, reintentos con el mismo SEQ,
TRACK a 20 Hz, latido), pero el transporte es un socket TCP local
hacia el controlador maestro de Webots (Webots/.../sofia_maestro_sim).

Las tramas son EXACTAMENTE las del protocolo (protocol.py).
Como TCP es un flujo de bytes y BLE manda paquetes, cada trama
viaja dentro de un "paquete" con un byte de longitud al inicio:

    +-----+---------------------------+
    | N   | N bytes (una trama)       |
    +-----+---------------------------+

Así el maestro recibe lo mismo que el ESP32 recibe por BLE
(una escritura = una trama) y valida igual.

EMULADOR DE CANAL (opcional)
----------------------------
Un socket local es perfecto (<1 ms, sin pérdidas). Con
channel_emulation = True se agregan retraso, pérdidas y bytes
dañados parecidos a un enlace BLE, para ver en la simulación
cómo trabajan los reintentos y los NACK.
"""

import asyncio
import random
import struct

from . import protocol as p
from .ble_link import BleLink


SIM_HOST = "127.0.0.1"
SIM_PORT = 5555

# -----------------------------
# EMULADOR DE CANAL (tipo BLE)
# -----------------------------

CHANNEL_DELAY_MS = 30        # retraso de cada sentido
CHANNEL_JITTER_MS = 10       # variación aleatoria del retraso (±)
CHANNEL_LOSS = 0.03          # probabilidad de perder una trama
CHANNEL_CORRUPT = 0.02       # probabilidad de dañar un byte (CRC)


class WebotsLink(BleLink):

    target_name = "Webots"

    def __init__(self, host=SIM_HOST, port=SIM_PORT, parent=None):

        super().__init__(parent=parent)

        self.host = host
        self.port = port

        # Se cambia desde la GUI (checkbox)
        self.channel_emulation = False

        self._reader_task = None


    # =============================================
    # CONEXIÓN
    # =============================================

    async def _connect(self):

        if self._state != "desconectado":
            return

        self._set_state("buscando")
        self.log.emit(f"Conectando a Webots en {self.host}:{self.port}...")

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=3.0
            )
        except Exception as error:
            self.log.emit(
                f"No se pudo conectar a Webots ({error}). "
                "¿Está abierto el mundo y corriendo la simulación?"
            )
            self._set_state("desconectado")
            return

        self._client = writer
        self._reader_task = self._loop.create_task(self._read_packets(reader))

        self._set_state("conectado")
        self.log.emit("Conectado a Webots")


    async def _disconnect(self):

        writer = self._client
        self._client = None

        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        if self._state != "desconectado":
            self._set_state("desconectado")
            self.log.emit("Desconectado de Webots")


    async def _read_packets(self, reader):
        """Recibe paquetes [N][trama] y los entrega como notificaciones."""

        try:
            while True:
                size = (await reader.readexactly(1))[0]
                data = await reader.readexactly(size)
                self._deliver(data)

        except asyncio.CancelledError:
            raise

        except Exception:
            # Webots cerró la conexión (simulación detenida o reiniciada)
            writer = self._client

            if writer is not None:
                self._reader_task = None
                self._on_disconnected(None)
                writer.close()


    # =============================================
    # TRANSPORTE
    # =============================================

    async def _write(self, frame):

        if not self.channel_emulation:
            self._raw_write(frame)
            return

        data = self._through_channel(frame)

        if data is None:
            return   # trama perdida (como si nunca hubiera llegado)

        self._loop.call_later(self._channel_delay(), self._raw_write, data)


    def _raw_write(self, frame):

        if self._client is None:
            return

        self._client.write(struct.pack("B", len(frame)) + frame)


    def _deliver(self, data):

        if not self.channel_emulation:
            self._on_notify(None, data)
            return

        data = self._through_channel(data)

        if data is not None:
            self._loop.call_later(self._channel_delay(), self._on_notify, None, data)


    # =============================================
    # EMULADOR DE CANAL
    # =============================================

    def _through_channel(self, data):

        if random.random() < CHANNEL_LOSS:
            return None

        if random.random() < CHANNEL_CORRUPT and len(data) > 1:
            data = bytearray(data)
            index = random.randrange(1, len(data))
            data[index] ^= 1 << random.randrange(8)
            data = bytes(data)

        return data


    def _channel_delay(self):
        delay_ms = CHANNEL_DELAY_MS + random.uniform(-CHANNEL_JITTER_MS, CHANNEL_JITTER_MS)
        return max(0.0, delay_ms) / 1000
