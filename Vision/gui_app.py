"""
GUI DE SOFIA - Sistema de visión

Interfaz gráfica (PySide6 / Qt) que:

    - Muestra el video en vivo con la detección dibujada.
    - Muestra el resultado: postura (JUEGO) o posición de la
      mano en el plano cartesiano (TRACKING).
    - Modo TEST: pruebas por gesto con cuenta regresiva y métricas;
      el estado se muestra en el panel "Pruebas", no sobre el video.
    - Permite INICIAR, PAUSAR, REANUDAR y DETENER el procesamiento.
    - Se conecta por Bluetooth (BLE) al ESP32 maestro y le envía
      las posturas y la posición de la mano.
    - Y/o, con el mismo protocolo, a la simulación de Webots (TCP local),
      y puede mostrar la cámara cenital de la simulación.
    - Gemelo digital: con los dos conectados, cada resultado se manda
      al robot real y a la simulación al mismo tiempo.

Arquitectura (ver docs/ARQUITECTURA_GUI.md):

    Hilo GUI  (esta ventana)  -> solo dibuja y atiende botones
    Hilo de visión  (VisionWorker / QThread) -> cámara + MediaPipe
    Hilo BLE  (BleLink / asyncio) -> comunicación con el ESP32
              (o WebotsLink: misma lógica, transporte TCP)
    Hilo cámara sim  (SimCameraClient / QThread) -> imágenes de Webots

Uso (dentro de Vision/, con el venv activo):
    python gui_app.py
"""

import math
import os
import sys

# Trabajar desde la carpeta de este archivo
# (rutas "models/..." relativas)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from comunicacion.ble_link import BleLink
from comunicacion.sim_link import WebotsLink
from deteccion.gesture_recognition import GESTURE_IDS, NO_GESTURE
from deteccion.vision_pipeline import MODE_GAME, MODE_TEST, MODE_TRACKING
from interfaz.vision_worker import (
    VisionWorker,
    STATE_LOADING,
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_STOPPED,
)
from interfaz.sim_camera import SimCameraClient


# -----------------------------
# ESTILO
# -----------------------------

COLORS = {
    STATE_STOPPED: "#8a8f98",
    STATE_LOADING: "#e0b341",
    STATE_RUNNING: "#3fb950",
    STATE_PAUSED: "#e0b341",
    "desconectado": "#8a8f98",
    "buscando": "#e0b341",
    "conectado": "#3fb950",
    "esperando": "#e0b341",
    "recibiendo": "#3fb950",
}

# Destinos a los que se pueden mandar los resultados
TARGET_ESP32 = "ESP32"
TARGET_WEBOTS = "Webots"

STYLE_SHEET = """
QMainWindow, QWidget { background: #15181d; color: #e6e8eb; }
QGroupBox {
    border: 1px solid #2b3038; border-radius: 8px;
    margin-top: 14px; padding: 10px 10px 8px 10px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa4b2; }
QPushButton {
    background: #232830; border: 1px solid #343b45; border-radius: 6px;
    padding: 7px 10px; font-weight: 600;
}
QPushButton:hover:enabled { background: #2c333d; }
QPushButton:disabled { color: #5c636d; border-color: #262b32; }
QPushButton#primary:enabled { background: #1f6feb; border-color: #1f6feb; color: white; }
QPushButton#danger:enabled { background: #3a1d20; border-color: #da3633; color: #ff7b72; }
QPlainTextEdit {
    background: #0f1115; border: 1px solid #2b3038; border-radius: 6px;
    font-family: Consolas, monospace; font-size: 11px;
}
QLabel#video { background: #0b0d10; border: 1px solid #2b3038; border-radius: 8px; color: #5c636d; }
QLabel#bigValue { font-size: 30px; font-weight: 700; color: #58a6ff; }
QLabel#muted { color: #9aa4b2; }
QLabel#testBig { padding: 4px 0; }
"""

# Gestos que se pueden probar en modo TEST (en orden de su número)
TEST_GESTURES = ["INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"]

TEST_COLORS = {
    "idle": "#9aa4b2",
    "countdown": "#e0b341",
    "active": "#ff7b72",
    "ok": "#3fb950",
    "fail": "#ff7b72",
}


def dot(color):
    return f'<span style="color:{color}; font-size:16px;">●</span>'


# =============================================
# VENTANA PRINCIPAL
# =============================================

class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("SOFIA - Sistema de visión")
        self.resize(1200, 720)

        self.worker = None
        self.worker_state = STATE_STOPPED
        self.mode = MODE_GAME
        self.last_sent_gesture = NO_GESTURE

        # Dos enlaces independientes con la MISMA lógica de protocolo.
        # Los resultados se mandan a TODOS los que estén conectados:
        #   solo ESP32  -> robot real
        #   solo Webots -> simulación (sin ESP32)
        #   los dos     -> gemelo digital
        self.links = {
            TARGET_ESP32: BleLink(parent=self),
            TARGET_WEBOTS: WebotsLink(parent=self),
        }

        for link in self.links.values():
            link.state_changed.connect(self.on_ble_state)
            link.log.connect(self.on_link_log)
            link.command_result.connect(self.on_command_result)

        # Cámara de la simulación (hilo propio, solo si se activa)
        self.sim_camera = None

        self._build_ui()
        self._update_controls()
        self._refresh_links()


    # =============================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =============================================

    def _build_ui(self):

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # -----------------------------
        # VIDEO (izquierda)
        # -----------------------------

        self.video_label = QLabel("Presiona INICIAR para abrir la cámara")
        self.video_label.setObjectName("video")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(480, 360)
        self.video_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Vista de la simulación (a la derecha del video, oculta
        # hasta que se active "Ver cámara de Webots")
        self.sim_label = QLabel("Esperando la cámara de Webots...")
        self.sim_label.setObjectName("video")
        self.sim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sim_label.setMinimumSize(320, 320)
        self.sim_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.sim_label.hide()

        views = QHBoxLayout()
        views.setSpacing(12)
        views.addWidget(self.video_label, stretch=3)
        views.addWidget(self.sim_label, stretch=2)
        layout.addLayout(views, stretch=1)

        # -----------------------------
        # PANEL LATERAL (derecha)
        # -----------------------------

        side = QVBoxLayout()
        side.setSpacing(4)

        side.addWidget(self._build_control_group())
        side.addWidget(self._build_mode_group())
        side.addWidget(self._build_result_group())
        side.addWidget(self._build_test_group())
        side.addWidget(self._build_ble_group())
        side.addWidget(self._build_log_group(), stretch=1)

        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(340)
        layout.addWidget(side_widget)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Listo")


    def _build_control_group(self):

        group = QGroupBox("Control de detección")
        grid = QGridLayout(group)

        self.btn_start = QPushButton("▶  Iniciar")
        self.btn_start.setObjectName("primary")
        self.btn_pause = QPushButton("⏸  Pausar")
        self.btn_resume = QPushButton("⏵  Reanudar")
        self.btn_stop = QPushButton("■  Detener")
        self.btn_stop.setObjectName("danger")

        self.btn_start.clicked.connect(self.start_detection)
        self.btn_pause.clicked.connect(self.pause_detection)
        self.btn_resume.clicked.connect(self.resume_detection)
        self.btn_stop.clicked.connect(self.stop_detection)

        grid.addWidget(self.btn_start, 0, 0)
        grid.addWidget(self.btn_pause, 0, 1)
        grid.addWidget(self.btn_resume, 1, 0)
        grid.addWidget(self.btn_stop, 1, 1)

        self.state_label = QLabel()
        self.state_label.setTextFormat(Qt.TextFormat.RichText)
        grid.addWidget(self.state_label, 2, 0, 1, 2)

        return group


    def _build_mode_group(self):

        group = QGroupBox("Modo")
        row = QHBoxLayout(group)

        self.radio_game = QRadioButton("Juego")
        self.radio_test = QRadioButton("Test")
        self.radio_tracking = QRadioButton("Tracking")
        self.radio_game.setChecked(True)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_game)
        self.mode_group.addButton(self.radio_test)
        self.mode_group.addButton(self.radio_tracking)
        self.mode_group.buttonClicked.connect(self.on_mode_clicked)

        row.addWidget(self.radio_game)
        row.addWidget(self.radio_test)
        row.addWidget(self.radio_tracking)

        return group


    def _build_result_group(self):

        group = QGroupBox("Resultado")
        box = QVBoxLayout(group)

        self.result_title = QLabel("Postura")
        self.result_title.setObjectName("muted")

        self.result_value = QLabel(NO_GESTURE)
        self.result_value.setObjectName("bigValue")

        self.result_detail = QLabel("")
        self.result_detail.setObjectName("muted")
        self.result_detail.setWordWrap(True)
        self.result_detail.setFont(QFont("Consolas", 9))

        self.stats_label = QLabel("FPS: --   Latencia: -- ms")
        self.stats_label.setObjectName("muted")

        box.addWidget(self.result_title)
        box.addWidget(self.result_value)
        box.addWidget(self.result_detail)
        box.addWidget(self.stats_label)

        return group


    def _build_test_group(self):

        # Solo visible en modo TEST
        group = QGroupBox("Pruebas")
        box = QVBoxLayout(group)

        self.test_label = QLabel()
        self.test_label.setObjectName("testBig")
        self.test_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.test_label.setTextFormat(Qt.TextFormat.RichText)
        self.test_label.setWordWrap(True)
        # Altura fija: el panel no "brinca" entre fases
        self.test_label.setFixedHeight(100)

        grid = QGridLayout()
        self.test_buttons = []

        for index, name in enumerate(TEST_GESTURES):
            button = QPushButton(name)
            button.clicked.connect(lambda _=False, n=name: self.start_trial(n))
            grid.addWidget(button, index // 3, index % 3)
            self.test_buttons.append(button)

        self.btn_cancel_trial = QPushButton("Cancelar")
        self.btn_cancel_trial.clicked.connect(self.cancel_trial)
        grid.addWidget(self.btn_cancel_trial, 1, 2)

        self.test_counts = QLabel()
        self.test_counts.setObjectName("muted")

        box.addWidget(self.test_label)
        box.addLayout(grid)
        box.addWidget(self.test_counts)

        self.test_group = group
        self.test_group.setVisible(False)
        self._set_test_idle()

        return group


    def _build_ble_group(self):

        group = QGroupBox("Robot (ESP32 / Webots)")
        grid = QGridLayout(group)

        # Una fila por destino: nombre, estado y botón
        self.link_rows = {}
        captions = {TARGET_ESP32: "ESP32", TARGET_WEBOTS: "Webots"}

        for row, name in enumerate(self.links):
            caption = QLabel(captions[name])
            state = QLabel()
            state.setTextFormat(Qt.TextFormat.RichText)
            button = QPushButton("Conectar")
            button.setMinimumWidth(112)
            button.clicked.connect(lambda _checked=False, n=name: self.toggle_link(n))

            grid.addWidget(caption, row, 0)
            grid.addWidget(state, row, 1)
            grid.addWidget(button, row, 2)
            self.link_rows[name] = (state, button)

        # Se enciende cuando los dos están conectados
        self.twin_label = QLabel()
        self.twin_label.setTextFormat(Qt.TextFormat.RichText)
        self.twin_label.setWordWrap(True)

        self.btn_ping = QPushButton("PING")
        self.btn_ping.setMinimumWidth(112)
        self.btn_ping.clicked.connect(self.ping_all)

        self.chk_send = QCheckBox("Enviar resultados")
        self.chk_send.setChecked(True)

        # Solo Webots: emular retraso y pérdidas como en BLE
        self.chk_channel = QCheckBox("Simular canal BLE en Webots")
        self.chk_channel.toggled.connect(self.on_channel_toggled)

        # Ver la cámara cenital de Webots (canal aparte)
        self.chk_sim_camera = QCheckBox("Ver cámara de Webots")
        self.chk_sim_camera.toggled.connect(self.toggle_sim_camera)

        grid.addWidget(self.twin_label, 2, 0, 1, 3)
        grid.addWidget(self.chk_send, 3, 0, 1, 2)
        grid.addWidget(self.btn_ping, 3, 2)
        grid.addWidget(self.chk_channel, 4, 0, 1, 3)
        grid.addWidget(self.chk_sim_camera, 5, 0, 1, 3)
        grid.setColumnStretch(1, 1)

        return group


    def _build_log_group(self):

        group = QGroupBox("Bitácora")
        box = QVBoxLayout(group)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(300)

        box.addWidget(self.log_view)

        return group


    # =============================================
    # CONTROLES DE DETECCIÓN
    # =============================================

    @Slot()
    def start_detection(self):

        if self.worker is not None:
            return

        self.worker = VisionWorker(camera_index=0, mode=self.mode)

        self.worker.frame_ready.connect(self.show_frame)
        self.worker.result_ready.connect(self.show_result)
        self.worker.stats_ready.connect(self.show_stats)
        self.worker.state_changed.connect(self.on_worker_state)
        self.worker.error.connect(self.on_worker_error)
        self.worker.test_status.connect(self.show_test_status)
        self.worker.report_ready.connect(self.on_report_ready)
        self.worker.finished.connect(self.on_worker_finished)

        self.worker.start()
        self.append_log("Detección iniciada")


    @Slot()
    def pause_detection(self):
        if self.worker is not None:
            self.worker.pause()
            self.append_log("Detección pausada")


    @Slot()
    def resume_detection(self):
        if self.worker is not None:
            self.worker.resume()
            self.append_log("Detección reanudada")


    @Slot()
    def stop_detection(self):

        if self.worker is None:
            return

        self.worker.stop()
        self.append_log("Deteniendo detección...")

        # El robot (real y/o simulado) pasa a estado seguro
        for link in self._targets():
            link.send_stop()


    def _update_controls(self):

        state = self.worker_state

        self.btn_start.setEnabled(state == STATE_STOPPED and self.worker is None)
        self.btn_pause.setEnabled(state == STATE_RUNNING)
        self.btn_resume.setEnabled(state == STATE_PAUSED)
        self.btn_stop.setEnabled(state in (STATE_RUNNING, STATE_PAUSED, STATE_LOADING))

        self.state_label.setText(f"{dot(COLORS[state])}  Estado: <b>{state}</b>")

        self._update_test_buttons()


    # =============================================
    # EVENTOS DEL HILO DE VISIÓN
    # =============================================

    @Slot(str)
    def on_worker_state(self, state):

        self.worker_state = state
        self._update_controls()

        if state == STATE_LOADING:
            self.video_label.setText("Cargando modelos de MediaPipe...")

        self.statusBar().showMessage(f"Detección: {state}")


    @Slot(str)
    def on_worker_error(self, message):
        self.append_log(f"ERROR: {message}")
        self.statusBar().showMessage(message)


    @Slot()
    def on_worker_finished(self):

        self.worker.deleteLater()
        self.worker = None
        self.worker_state = STATE_STOPPED
        self._update_controls()

        self.video_label.clear()
        self.video_label.setText("Detección detenida")
        self.append_log("Detección detenida")

        self._set_test_idle()


    @Slot(QImage)
    def show_frame(self, image):

        pixmap = QPixmap.fromImage(image).scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)


    @Slot(float, float)
    def show_stats(self, fps, latency_ms):
        self.stats_label.setText(f"FPS: {fps:.1f}   Latencia: {latency_ms:.0f} ms")


    @Slot(object)
    def show_result(self, result):

        if result.mode == MODE_TRACKING:
            self._show_tracking(result)
        else:
            self._show_game(result)


    def _show_game(self, result):

        self.result_title.setText("Postura")
        self.result_value.setText(result.gesture)
        self.result_detail.setText(
            "Persona detectada" if result.person_detected else "Persona no detectada"
        )

        # Se envía solo cuando APARECE una postura nueva
        if result.gesture != self.last_sent_gesture:

            if result.gesture != NO_GESTURE:
                for link in self._targets():
                    link.send_pose(GESTURE_IDS[result.gesture])

            self.last_sent_gesture = result.gesture


    def _show_tracking(self, result):

        self.result_title.setText("Posición de la mano")

        if not result.hand_positions:
            self.result_value.setText("Sin mano")
            self.result_detail.setText("")
            return

        lines = []

        for position in result.hand_positions:
            source = "" if position.source == "mano" else f"  [{position.source}]"
            lines.append(
                f"{position.label}{source}\n"
                f"  x={position.x:+.0f}  y={position.y:+.0f} px\n"
                f"  norm=({position.x_norm:+.2f}, {position.y_norm:+.2f})\n"
                f"  |v|={position.magnitude:.0f} px  ang={position.angle:.1f}°"
            )

        main = self._main_hand(result.hand_positions)

        self.result_value.setText(f"({main.x_norm:+.2f}, {main.y_norm:+.2f})")
        self.result_detail.setText("\n".join(lines))

        for link in self._targets():
            link.send_track(main)


    @staticmethod
    def _main_hand(positions):
        # Se prefiere la mano derecha y las posiciones
        # medidas (no estimadas)
        return sorted(
            positions,
            key=lambda p: (p.source == "memoria", p.label != "DERECHA"),
        )[0]


    def _targets(self):
        """Enlaces a los que se mandan los resultados (todos los conectados)."""
        if not self.chk_send.isChecked():
            return []
        return [link for link in self.links.values() if link.connected]


    # =============================================
    # MODO
    # =============================================

    def on_mode_clicked(self, _button=None):

        if self.radio_tracking.isChecked():
            mode = MODE_TRACKING
        elif self.radio_test.isChecked():
            mode = MODE_TEST
        else:
            mode = MODE_GAME

        if mode == self.mode:
            return

        self.mode = mode
        self.last_sent_gesture = NO_GESTURE

        self.test_group.setVisible(mode == MODE_TEST)
        self._set_test_idle()

        if self.worker is not None:
            self.worker.set_mode(mode)

        self.result_value.setText(NO_GESTURE)
        self.result_detail.setText("")
        self.append_log(f"Modo: {mode}")

        for link in self._targets():
            link.send_mode(mode)


    # =============================================
    # PRUEBAS (MODO TEST)
    # =============================================

    def start_trial(self, gesture):
        if self.worker is not None and self.mode == MODE_TEST:
            self.worker.start_trial(gesture)
            self.append_log(f"Prueba de {gesture}")


    @Slot()
    def cancel_trial(self):
        if self.worker is not None:
            self.worker.cancel_trial()
            self.append_log("Prueba cancelada")


    def _set_test_idle(self):
        self._test_state = "idle"
        self._show_test_text("Listo", "Elige un gesto para probar", "idle")
        self.test_counts.setText("Intentos: 0   Aciertos: 0")
        self._update_test_buttons()


    def _show_test_text(self, main, detail, color_key):
        # Línea principal grande + detalle en letra chica
        color = TEST_COLORS[color_key]
        self.test_label.setText(
            f'<div style="color:{color}; font-size:24px; font-weight:700;">{main}</div>'
            f'<div style="color:{color}; font-size:12px;">{detail}</div>'
        )


    def _update_test_buttons(self):

        running = self.worker_state == STATE_RUNNING
        free = self._test_state in ("idle", "result")

        for button in self.test_buttons:
            button.setEnabled(running and free)

        self.btn_cancel_trial.setEnabled(running and not free)


    @Slot(object)
    def show_test_status(self, status):

        state = status["state"]
        expected = status["expected"]
        remaining = status["remaining"]

        # -----------------------------
        # LETRERO PRINCIPAL
        # -----------------------------

        if state == "countdown":
            # Cuenta regresiva 3, 2, 1
            self._show_test_text(
                f"{max(1, math.ceil(remaining))}",
                f"Prepárate: {expected}",
                "countdown",
            )

        elif state == "active":
            self._show_test_text(
                f"¡YA!  {expected}",
                f"Quedan {remaining:.1f} s",
                "active",
            )

        elif state == "result" and status["last_result"]:
            result = status["last_result"]
            if result["correcto"]:
                detail = f"{result['detectado']} en {result['tiempo_respuesta_s']:.2f} s"
                if result.get("tiempo_reaccion_s") is not None:
                    detail += (
                        f"<br>Reacción {result['tiempo_reaccion_s']:.2f} s · "
                        f"Procesado {result['tiempo_reconocimiento_s']:.2f} s"
                        f"<br>{result['frames_reconocimiento']} frames · "
                        f"{result['procesamiento_reconocimiento_ms']:.0f} ms de cómputo"
                    )
                elif result.get("frames_hasta_respuesta") is not None:
                    detail += (
                        f"<br>{result['frames_hasta_respuesta']} frames · "
                        f"{result['tiempo_procesamiento_ms']:.0f} ms de procesamiento"
                    )
                self._show_test_text("ACIERTO", detail, "ok")
            else:
                detected = "nada" if result["detectado"] == "NINGUNO" else result["detectado"]
                self._show_test_text(
                    "FALLO",
                    f"Esperado {result['esperado']} · detectó {detected}",
                    "fail",
                )

        else:
            self._show_test_text("Listo", "Elige un gesto para probar", "idle")

        # -----------------------------
        # CONTADORES
        # -----------------------------

        counts = f"Intentos: {status['total']}   Aciertos: {status['hits']}"
        if status["rate"] is not None:
            counts += f" ({status['rate']:.0f}%)"
        if status["fps"]:
            counts += f"   FPS prom.: {status['fps']:.1f}"
        self.test_counts.setText(counts)

        if state != self._test_state:
            self._test_state = state
            self._update_test_buttons()


    @Slot(str)
    def on_report_ready(self, json_path):
        name = os.path.splitext(os.path.basename(json_path))[0]
        self.append_log(f"Métricas guardadas: {json_path}")
        self.append_log(f"Reporte: metrics/reportes/{name}/")
        self.statusBar().showMessage(f"Reporte generado: metrics/reportes/{name}/")


    # =============================================
    # BLUETOOTH
    # =============================================

    def toggle_link(self, name):

        link = self.links[name]

        if link.connected:
            link.disconnect_device()
        else:
            link.connect_device()


    def ping_all(self):
        for link in self.links.values():
            if link.connected:
                link.ping()


    def _link_name(self, link):
        for name, candidate in self.links.items():
            if candidate is link:
                return name
        return "?"


    @Slot(str)
    def on_ble_state(self, state):

        link = self.sender()

        # Al conectar, informar el modo actual
        if state == "conectado" and link in self.links.values():
            link.send_mode(self.mode)

        self._refresh_links()


    def _refresh_links(self):

        for name, link in self.links.items():
            state_label, button = self.link_rows[name]
            state = link.state

            state_label.setText(f"{dot(COLORS[state])}  {state.capitalize()}")
            button.setText("Desconectar" if state == "conectado" else "Conectar")
            button.setEnabled(state != "buscando")

        connected = [name for name, link in self.links.items() if link.connected]

        self.btn_ping.setEnabled(bool(connected))

        if len(connected) == 2:
            self.twin_label.setText(
                f"{dot(COLORS['conectado'])}  <b>Gemelo digital</b>: "
                "robot real + simulación"
            )
        elif connected == [TARGET_WEBOTS]:
            self.twin_label.setText("Solo simulación (sin ESP32)")
        elif connected == [TARGET_ESP32]:
            self.twin_label.setText("Solo robot real")
        else:
            self.twin_label.setText("Sin conexión")


    @Slot(str)
    def on_link_log(self, text):
        self.append_log(f"[{self._link_name(self.sender())}] {text}")


    @Slot(bool)
    def on_channel_toggled(self, checked):
        self.links[TARGET_WEBOTS].channel_emulation = checked
        self.append_log(
            "Canal BLE simulado: retraso, pérdidas y errores activados"
            if checked else "Canal BLE simulado desactivado"
        )


    # =============================================
    # CÁMARA DE LA SIMULACIÓN
    # =============================================

    @Slot(bool)
    def toggle_sim_camera(self, checked):

        if checked and self.sim_camera is None:
            self.sim_camera = SimCameraClient(parent=self)
            self.sim_camera.frame_ready.connect(self.show_sim_frame)
            self.sim_camera.status.connect(self.on_sim_camera_status)
            self.sim_camera.start()
            self.sim_label.show()

        elif not checked and self.sim_camera is not None:
            self.sim_camera.stop()
            self.sim_camera.wait(2000)
            self.sim_camera = None
            self.sim_label.clear()
            self.sim_label.setText("Esperando la cámara de Webots...")
            self.sim_label.hide()


    @Slot(QImage)
    def show_sim_frame(self, image):

        pixmap = QPixmap.fromImage(image).scaled(
            self.sim_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.sim_label.setPixmap(pixmap)


    @Slot(str)
    def on_sim_camera_status(self, status):

        if status == "esperando":
            self.sim_label.clear()
            self.sim_label.setText(
                "Esperando la cámara de Webots...\n(abre el mundo y corre la simulación)"
            )


    @Slot(str, bool, str)
    def on_command_result(self, name, ok, detail):
        mark = "✔" if ok else "✖"
        self.append_log(f"[{self._link_name(self.sender())}] {mark} {name}: {detail}")


    # =============================================
    # BITÁCORA
    # =============================================

    @Slot(str)
    def append_log(self, text):
        self.log_view.appendPlainText(text)


    # =============================================
    # CIERRE
    # =============================================

    def closeEvent(self, event):

        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(3000)

        if self.sim_camera is not None:
            self.sim_camera.stop()
            self.sim_camera.wait(2000)

        for link in self.links.values():
            link.shutdown()

        super().closeEvent(event)


# =============================================
# INICIO
# =============================================

def main():

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
