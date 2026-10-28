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
    - Latido: si no llegó nada del ESP32 en 1 s, se manda un PING
      (el ESP32 lo contesta con ACK, así se sabe que sigue vivo).
    - Enlace perdido: si en 3 s no llega ninguna respuesta, se cierra
      la conexión aunque el sistema operativo aún la crea abierta.
    - Reconexión automática: si la conexión se pierde o falla y el
      usuario no pidió desconectar, se reintenta sola con esperas
      de 1, 2, 4, 8 y luego 10 s. El botón "Cancelar" la detiene.

La parte de transporte (conectar, escribir y recibir) está separada
en _connect(), _disconnect() y _write(). WebotsLink (sim_link.py)
hereda de esta clase y solo cambia el transporte (TCP en lugar de
BLE): las reglas del protocolo son exactamente las mismas.
"""

import asyncio
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import protocol as p


class BleLink(QObject):

    # Nombre del destino para los mensajes de la bitácora
    target_name = "ESP32"

    # "desconectado", "buscando", "conectado"
    state_changed = Signal(str)

    # Texto para la bitácora de la GUI
    log = Signal(str)

    # (nombre_comando, ok, detalle)
    command_result = Signal(str, bool, str)

    # Resultado completo de un comando con ACK (dict), para el
    # registro de la sesión: comando, seq, ok, detalle, intentos,
    # rtt_ms, cola_ms (desde que se pidió hasta el ACK) y tag
    command_done = Signal(object)

    # Eventos del enlace para el registro: (tipo, detalle)
    # tipos: "conectado", "desconectado", "perdido", "reintento",
    #        "reconectado", "error"
    link_event = Signal(str, str)


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
        self._last_rx_time = 0.0

        # -----------------------------
        # RECONEXIÓN AUTOMÁTICA
        # -----------------------------

        # True mientras el usuario quiera estar conectado
        # (se activa con "Conectar" y se apaga con "Desconectar")
        self._want_connected = False
        self._reconnect_attempt = 0
        self._next_reconnect = 0.0
        # Momento en que se perdió la conexión (para medir caídas)
        self._lost_since = None

        # Contadores de la sesión
        self.stats = {
            "tramas_track": 0,
            "latidos": 0,
            "reintentos_ack": 0,
            "nacks": 0,
            "caidas": 0,
            "reconexiones": 0,
        }

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
            self._loop.create_task(self._reconnect_supervisor()),
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


    @property
    def state(self):
        """'desconectado', 'buscando' o 'conectado'."""
        return self._state


    @property
    def reconnecting(self):
        """True si está desconectado pero va a reintentar solo."""
        return self._want_connected and self._state != "conectado"


    @property
    def reconnect_attempt(self):
        return self._reconnect_attempt


    def connect_device(self):
        self._want_connected = True
        self._reconnect_attempt = 0
        self._submit(self._connect())


    def disconnect_device(self):
        """Desconexión pedida por el usuario: no se reintenta."""
        self._want_connected = False
        self._reconnect_attempt = 0
        self._lost_since = None
        self._submit(self._disconnect())
        # Refrescar la GUI aunque ya estuviera desconectado
        self.state_changed.emit(self._state)


    def ping(self):
        self._queue_command(p.TYPE_PING)


    def send_pose(self, pose_id, tag=None):
        """tag: dato libre que regresa en command_done (ej. la postura y
        el momento en que se detectó, para medir el ciclo completo)."""
        self._queue_command(p.TYPE_POSE, p.pose_payload(pose_id), tag)


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

        self.stats["tramas_track"] += 1
        self._submit(self._send_frame(p.TYPE_TRACK, payload, log_it=False))


    def shutdown(self):
        """Desconecta y detiene el hilo (al cerrar la app)."""

        self._want_connected = False

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


    def _queue_command(self, frame_type, payload=b"", tag=None):

        name = p.TYPE_NAMES[frame_type]
        queued_at = time.monotonic()

        if not self.connected:
            self.command_result.emit(name, False, "Sin conexión")
            self._emit_done(name, None, False, "Sin conexión", 0, None, queued_at, tag)
            return

        def put():
            try:
                self._commands.put_nowait((frame_type, payload, queued_at, tag))
            except asyncio.QueueFull:
                self.log.emit("Cola de comandos llena: comando descartado")
                self._emit_done(name, None, False, "Cola llena", 0, None, queued_at, tag)

        self._loop.call_soon_threadsafe(put)


    def _set_state(self, state):
        self._state = state
        self.state_changed.emit(state)


    def _emit_done(self, name, seq, ok, detail, attempts, rtt_ms, queued_at, tag):
        self.command_done.emit({
            "comando": name,
            "seq": seq,
            "ok": ok,
            "detalle": detail,
            "intentos": attempts,
            "rtt_ms": rtt_ms,
            "cola_ms": (time.monotonic() - queued_at) * 1000,
            "tag": tag,
        })


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
                self.link_event.emit("error", "ESP32 no encontrado")
                self._set_state("desconectado")
                return

            self._client = BleakClient(
                device,
                disconnected_callback=self._on_disconnected,
            )

            await self._client.connect()
            await self._client.start_notify(p.TX_CHAR_UUID, self._on_notify)

            self._on_connected(f"{device.name} ({device.address})")

        except Exception as error:
            self.log.emit(f"Error al conectar: {error}")
            self.link_event.emit("error", f"Error al conectar: {error}")
            self._client = None
            self._set_state("desconectado")


    def _on_connected(self, description):
        """Se llama al terminar de conectar (BLE o TCP)."""

        self._last_rx_time = time.monotonic()
        self._reconnect_attempt = 0
        self._set_state("conectado")
        self.log.emit(f"Conectado a {description}")

        if self._lost_since is not None:
            down_s = time.monotonic() - self._lost_since
            self._lost_since = None
            self.stats["reconexiones"] += 1
            self.log.emit(f"Reconectado tras {down_s:.1f} s sin enlace")
            self.link_event.emit("reconectado", f"{down_s:.1f}")
        else:
            self.link_event.emit("conectado", description)


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


    def _on_disconnected(self, client):

        # Aviso tardío de un cliente viejo (ya se reconectó con otro)
        if client is not None and client is not self._client:
            return

        self._client = None
        reason = getattr(self, "_mark_lost_reason", None)
        self._mark_lost_reason = None

        # Despertar al comando que esperaba ACK
        if self._pending is not None:
            future = self._pending[2]
            self._loop.call_soon_threadsafe(
                lambda: future.done() or future.set_result(None)
            )

        if self._state == "desconectado":
            return

        if not self._want_connected:
            # Desconexión pedida por el usuario: no es una caída
            self._set_state("desconectado")
            self.log.emit("Desconectado")
            return

        self._mark_lost(reason or f"Se perdió la conexión con {self.target_name}")


    def _mark_lost(self, reason):
        """Caída que el usuario NO pidió: se avisa y se reintenta."""

        self.stats["caidas"] += 1

        if self._lost_since is None:
            self._lost_since = time.monotonic()

        self._next_reconnect = time.monotonic() + p.RECONNECT_DELAYS_S[0]
        self._set_state("desconectado")
        self.log.emit(reason)
        self.link_event.emit("perdido", reason)


    async def _reconnect_supervisor(self):
        """Reintenta conectar mientras el usuario quiera estar conectado."""

        while True:

            await asyncio.sleep(0.25)

            if not self._want_connected or self._state != "desconectado":
                continue

            now = time.monotonic()

            if now < self._next_reconnect:
                continue

            self._reconnect_attempt += 1
            attempt = self._reconnect_attempt

            if self._lost_since is None:
                # Falló el primer intento (ej. ESP32 apagado al iniciar)
                self._lost_since = now

            self.log.emit(f"Reintentando conexión (intento {attempt})...")
            self.link_event.emit("reintento", str(attempt))

            try:
                await self._connect()
            except Exception as error:   # nunca debe tumbar el hilo
                self.log.emit(f"Error al reconectar: {error}")
                self._set_state("desconectado")

            if self._state != "conectado":
                index = min(attempt, len(p.RECONNECT_DELAYS_S)) - 1
                delay = p.RECONNECT_DELAYS_S[index]
                self._next_reconnect = time.monotonic() + delay
                self.log.emit(f"Sin éxito; siguiente intento en {delay} s")


    # =============================================
    # ENVÍO
    # =============================================

    async def _send_frame(self, frame_type, payload=b"", seq=None, log_it=True):

        if self._client is None or not self.connected:
            return None

        seq = self._next_seq() if seq is None else seq
        frame = p.build_frame(frame_type, seq, payload)

        try:
            await self._write(frame)
        except Exception as error:
            self.log.emit(f"Error al enviar: {error}")
            return None

        self._last_tx_time = time.monotonic()

        if log_it:
            self.log.emit(f"→ {p.Frame(frame_type, seq, payload)}")

        return seq


    async def _write(self, frame):
        # Una escritura BLE = una trama completa
        await self._client.write_gatt_char(
            p.RX_CHAR_UUID, frame, response=False
        )


    async def _command_worker(self):
        """Envía los comandos uno por uno esperando su ACK."""

        while True:

            frame_type, payload, queued_at, tag = await self._commands.get()
            name = p.TYPE_NAMES[frame_type]

            try:
                ok, detail, seq, attempts, rtt_ms = await self._send_with_ack(
                    frame_type, payload
                )
            except Exception as error:   # nunca debe tumbar el hilo
                ok, detail, seq, attempts, rtt_ms = False, f"Error: {error}", None, 0, None

            self.command_result.emit(name, ok, detail)
            self._emit_done(name, seq, ok, detail, attempts, rtt_ms, queued_at, tag)


    async def _send_with_ack(self, frame_type, payload):
        """Regresa (ok, detalle, seq, intentos, rtt_ms)."""

        # El mismo SEQ en todos los reintentos: así el ESP32
        # reconoce duplicados y no ejecuta dos veces
        seq = self._next_seq()

        for attempt in range(1, p.MAX_RETRIES + 1):

            future = self._loop.create_future()
            self._pending = (frame_type, seq, future)

            sent = await self._send_frame(frame_type, payload, seq=seq)

            if sent is None:
                self._pending = None
                return False, "Sin conexión", seq, attempt, None

            start = time.monotonic()

            try:
                response = await asyncio.wait_for(future, p.ACK_TIMEOUT_S)
            except asyncio.TimeoutError:
                self.log.emit(f"Sin ACK (intento {attempt}/{p.MAX_RETRIES})")
                self.stats["reintentos_ack"] += 1
                continue
            finally:
                self._pending = None

            if response is None:
                return False, "Conexión perdida", seq, attempt, None

            kind, error_code = response
            elapsed_ms = (time.monotonic() - start) * 1000

            if kind == "ACK":
                return True, f"ACK en {elapsed_ms:.0f} ms", seq, attempt, elapsed_ms

            self.stats["nacks"] += 1

            reason = p.ERROR_NAMES.get(error_code, f"0x{error_code:02X}")

            # Un error de CRC se puede deber a ruido: reintentar
            if error_code in (p.ERR_CRC, p.ERR_BUSY):
                self.log.emit(f"NACK ({reason}), reintentando")
                continue

            return False, f"NACK: {reason}", seq, attempt, elapsed_ms

        return False, f"Sin respuesta de {self.target_name}", seq, p.MAX_RETRIES, None


    async def _heartbeat(self):
        """
        Latido y detección de enlace perdido.

        Se mira lo RECIBIDO (no lo enviado): en TRACKING la PC manda
        TRACK sin parar, pero esos no llevan ACK; sin este PING no se
        sabría si el ESP32 sigue contestando.
        """

        last_ping = 0.0

        while True:

            await asyncio.sleep(p.HEARTBEAT_INTERVAL_S / 4)

            if not self.connected:
                continue

            now = time.monotonic()
            silent = now - self._last_rx_time

            # Nada recibido en 3 s: el enlace está muerto aunque el
            # sistema operativo no lo haya notado todavía
            if silent >= p.LINK_LOST_S:
                await self._disconnect_lost(
                    f"Sin respuesta de {self.target_name} en {silent:.1f} s: enlace perdido"
                )
                continue

            if (
                silent >= p.HEARTBEAT_INTERVAL_S
                and now - last_ping >= p.HEARTBEAT_INTERVAL_S
                and self._commands.empty()
                and self._pending is None
            ):
                # Latido silencioso: no se registra en la bitácora
                last_ping = now
                self.stats["latidos"] += 1
                await self._send_frame(p.TYPE_PING, log_it=False)


    async def _disconnect_lost(self, reason):
        """Cierra la conexión muerta y deja que el supervisor reconecte."""

        # _disconnect() pondría "desconectado" como si lo pidiera el
        # usuario; aquí se marca primero como caída
        client = self._client
        self._mark_lost_reason = reason
        self._on_disconnected(None)

        if client is not None:
            try:
                await self._close_transport(client)
            except Exception:
                pass


    async def _close_transport(self, client):
        await client.disconnect()


    # =============================================
    # RECEPCIÓN (notificaciones del ESP32)
    # =============================================

    def _on_notify(self, _sender, data):

        # Cualquier cosa que llegue demuestra que el otro lado vive
        self._last_rx_time = time.monotonic()

        try:
            frame = p.parse_frame(data)
        except p.ProtocolError as error:
            self.log.emit(f"Trama inválida de {self.target_name}: {error}")
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
