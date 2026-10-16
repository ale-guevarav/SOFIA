"""
ENLACE BLUETOOTH LOW ENERGY PC -> ESP32 MAESTRO - SOFIA

Maneja la conexión BLE con el ESP32 maestro usando la librería bleak.

bleak funciona con asyncio, así que todo lo de Bluetooth corre
en un HILO PROPIO con su propio event loop. La GUI solo llama
métodos como send_pose() o ping(); estos programan el trabajo
en ese hilo y regresan de inmediato (la interfaz nunca se traba).

Los resultados llegan a la GUI por señales de Qt.

Reglas que implementa (ver docs/PROTOCOLO_COMUNICACION.md):
    - Comandos POSE, PING, MODE y STOP: uno a la vez, esperan ACK
      (300 ms) y se reintentan hasta 3 veces con el mismo SEQ.
    - TRACK: sin ACK, máximo 20 por segundo.
    - Latido: si no se envió nada en 1 s, se manda un PING.
"""

import asyncio
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import protocol as p


class BleLink(QObject):

    # "desconectado", "buscando", "conectado"
    state_changed = Signal(str)

    # Texto para la bitácora de la GUI
    log = Signal(str)

    # (nombre_comando, ok, detalle)
    command_result = Signal(str, bool, str)


    def __init__(self, device_name=p.DEVICE_NAME, parent=None):

        super().__init__(parent)

        self.device_name = device_name

        self._client = None
        self._seq = 0
        self._state = "desconectado"

        # Comando en espera de ACK: (tipo, seq, future)
        self._pending = None

        self._last_track_time = 0.0
        self._last_tx_time = 0.0

        # -----------------------------
        # HILO CON EVENT LOOP PROPIO
        # -----------------------------

        self._loop = asyncio.new_event_loop()

        self._thread = threading.Thread(
            target=self._run_loop,
            name="BleLink",
            daemon=True,
        )
        self._thread.start()

        # Cola de comandos (se crea dentro del loop)
        self._commands = None
        asyncio.run_coroutine_threadsafe(self._setup(), self._loop)


    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


    async def _setup(self):
        self._commands = asyncio.Queue(maxsize=20)
        self._tasks = [
            self._loop.create_task(self._command_worker()),
            self._loop.create_task(self._heartbeat()),
        ]


    async def _cancel_tasks(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


    # =============================================
    # API PARA LA GUI (se llama desde el hilo de Qt)
    # =============================================

    @property
    def connected(self):
        return self._state == "conectado"


    def connect_device(self):
        self._submit(self._connect())


    def disconnect_device(self):
        self._submit(self._disconnect())


    def ping(self):
        self._queue_command(p.TYPE_PING)


    def send_pose(self, pose_id):
        self._queue_command(p.TYPE_POSE, p.pose_payload(pose_id))


    def send_mode(self, mode_name):
        self._queue_command(p.TYPE_MODE, p.mode_payload(mode_name))


    def send_stop(self):
        self._queue_command(p.TYPE_STOP)


    def send_track(self, hand_position):
        """
        Envía la posición de una mano (HandPosition).
        Se descartan los envíos que excedan 20 Hz.
        """

        if not self.connected:
            return

        now = time.monotonic()

        if now - self._last_track_time < p.TRACK_MIN_INTERVAL_S:
            return

        self._last_track_time = now

        payload = p.track_payload(
            p.HAND_IDS.get(hand_position.label, 0),
            hand_position.x_norm,
            hand_position.y_norm,
            hand_position.magnitude_norm,
            hand_position.angle,
        )

        self._submit(self._send_frame(p.TYPE_TRACK, payload, log_it=False))


    def shutdown(self):
        """Desconecta y detiene el hilo (al cerrar la app)."""

        for coroutine, timeout in ((self._disconnect(), 3), (self._cancel_tasks(), 1)):
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            try:
                future.result(timeout=timeout)
            except Exception:
                pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)


    # =============================================
    # UTILIDADES INTERNAS
    # =============================================

    def _submit(self, coroutine):
        asyncio.run_coroutine_threadsafe(coroutine, self._loop)


    def _queue_command(self, frame_type, payload=b""):

        if not self.connected:
            self.command_result.emit(
                p.TYPE_NAMES[frame_type], False, "Sin conexión"
            )
            return

        def put():
            try:
                self._commands.put_nowait((frame_type, payload))
            except asyncio.QueueFull:
                self.log.emit("Cola de comandos llena: comando descartado")

        self._loop.call_soon_threadsafe(put)


    def _set_state(self, state):
        self._state = state
        self.state_changed.emit(state)


    def _next_seq(self):
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq


    # =============================================
    # CONEXIÓN
    # =============================================

    async def _connect(self):

        if self._state != "desconectado":
            return

        # Import aquí para que la GUI abra aunque
        # bleak no esté instalado
        from bleak import BleakClient, BleakScanner

        self._set_state("buscando")
        self.log.emit(f"Buscando '{self.device_name}'...")

        try:
            device = await BleakScanner.find_device_by_name(
                self.device_name, timeout=8.0
            )

            if device is None:
                self.log.emit("No se encontró el ESP32. ¿Está encendido y cerca?")
                self._set_state("desconectado")
                return

            self._client = BleakClient(
                device,
                disconnected_callback=self._on_disconnected,
            )

            await self._client.connect()
            await self._client.start_notify(p.TX_CHAR_UUID, self._on_notify)

            self._set_state("conectado")
            self.log.emit(f"Conectado a {device.name} ({device.address})")

        except Exception as error:
            self.log.emit(f"Error al conectar: {error}")
            self._client = None
            self._set_state("desconectado")


    async def _disconnect(self):

        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass

        self._client = None

        if self._state != "desconectado":
            self._set_state("desconectado")
            self.log.emit("Desconectado")


    def _on_disconnected(self, _client):

        self._client = None

        # Despertar al comando que esperaba ACK
        if self._pending is not None:
            future = self._pending[2]
            self._loop.call_soon_threadsafe(
                lambda: future.done() or future.set_result(None)
            )

        if self._state != "desconectado":
            self._set_state("desconectado")
            self.log.emit("Se perdió la conexión con el ESP32")


    # =============================================
    # ENVÍO
    # =============================================

    async def _send_frame(self, frame_type, payload=b"", seq=None, log_it=True):

        if self._client is None or not self.connected:
            return None

        seq = self._next_seq() if seq is None else seq
        frame = p.build_frame(frame_type, seq, payload)

        try:
            # Una escritura BLE = una trama completa
            await self._client.write_gatt_char(
                p.RX_CHAR_UUID, frame, response=False
            )
        except Exception as error:
            self.log.emit(f"Error al enviar: {error}")
            return None

        self._last_tx_time = time.monotonic()

        if log_it:
            self.log.emit(f"→ {p.Frame(frame_type, seq, payload)}")

        return seq


    async def _command_worker(self):
        """Envía los comandos uno por uno esperando su ACK."""

        while True:

            frame_type, payload = await self._commands.get()
            name = p.TYPE_NAMES[frame_type]

            ok, detail = await self._send_with_ack(frame_type, payload)

            self.command_result.emit(name, ok, detail)


    async def _send_with_ack(self, frame_type, payload):

        # El mismo SEQ en todos los reintentos: así el ESP32
        # reconoce duplicados y no ejecuta dos veces
        seq = self._next_seq()

        for attempt in range(1, p.MAX_RETRIES + 1):

            future = self._loop.create_future()
            self._pending = (frame_type, seq, future)

            sent = await self._send_frame(frame_type, payload, seq=seq)

            if sent is None:
                self._pending = None
                return False, "Sin conexión"

            start = time.monotonic()

            try:
                response = await asyncio.wait_for(future, p.ACK_TIMEOUT_S)
            except asyncio.TimeoutError:
                self.log.emit(f"Sin ACK (intento {attempt}/{p.MAX_RETRIES})")
                continue
            finally:
                self._pending = None

            if response is None:
                return False, "Conexión perdida"

            kind, error_code = response
            elapsed_ms = (time.monotonic() - start) * 1000

            if kind == "ACK":
                return True, f"ACK en {elapsed_ms:.0f} ms"

            reason = p.ERROR_NAMES.get(error_code, f"0x{error_code:02X}")

            # Un error de CRC se puede deber a ruido: reintentar
            if error_code in (p.ERR_CRC, p.ERR_BUSY):
                self.log.emit(f"NACK ({reason}), reintentando")
                continue

            return False, f"NACK: {reason}"

        return False, "Sin respuesta del ESP32"


    async def _heartbeat(self):
        """Manda PING si la línea lleva 1 s en silencio."""

        while True:

            await asyncio.sleep(p.HEARTBEAT_INTERVAL_S / 2)

            idle = time.monotonic() - self._last_tx_time

            if (
                self.connected
                and idle >= p.HEARTBEAT_INTERVAL_S
                and self._commands.empty()
                and self._pending is None
            ):
                # Latido silencioso: no se registra en la bitácora
                await self._send_frame(p.TYPE_PING, log_it=False)


    # =============================================
    # RECEPCIÓN (notificaciones del ESP32)
    # =============================================

    def _on_notify(self, _sender, data):

        try:
            frame = p.parse_frame(data)
        except p.ProtocolError as error:
            self.log.emit(f"Trama inválida del ESP32: {error}")
            return

        try:
            if frame.type == p.TYPE_ACK:
                acked_type, acked_seq = p.decode_ack(frame)
                self._resolve(acked_type, acked_seq, ("ACK", None))

            elif frame.type == p.TYPE_NACK:
                nacked_type, nacked_seq, code = p.decode_nack(frame)
                self.log.emit(
                    f"← NACK {p.TYPE_NAMES.get(nacked_type, nacked_type)} "
                    f"seq={nacked_seq}: {p.ERROR_NAMES.get(code, code)}"
                )
                self._resolve(nacked_type, nacked_seq, ("NACK", code))

            else:
                self.log.emit(f"← Mensaje inesperado: {frame}")

        except p.ProtocolError as error:
            self.log.emit(f"Respuesta mal formada: {error}")


    def _resolve(self, frame_type, seq, response):

        # Solo cuenta si responde al comando que se espera
        if self._pending is None:
            return

        pending_type, pending_seq, future = self._pending

        if pending_type == frame_type and pending_seq == seq:
            # El future pertenece al loop de BLE: se resuelve ahí
            self._loop.call_soon_threadsafe(
                lambda: future.done() or future.set_result(response)
            )
