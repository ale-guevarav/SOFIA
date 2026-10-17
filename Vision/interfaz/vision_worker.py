"""
HILO DE PROCESAMIENTO DE VIDEO - SOFIA

QThread que lee la cámara y ejecuta el VisionPipeline FUERA
del hilo de la interfaz. Así la GUI nunca se congela, aunque
MediaPipe tarde varios milisegundos por frame.

Comunicación con la GUI (thread-safe):

    GUI -> hilo:  pause(), resume(), stop(), set_mode(),
                  start_trial(), cancel_trial()
                  (protegidos con QMutex + QWaitCondition)

    hilo -> GUI:  señales de Qt (frame_ready, result_ready,
                  test_status, ...) que Qt entrega en el hilo
                  de la GUI.

Modo TEST: el hilo registra las métricas (metrics_logger) igual
que main.py, pero el estado de la prueba (cuenta regresiva, YA,
acierto/fallo) se manda a la GUI en lugar de dibujarse en el video.
Al detener se guarda el JSON y se genera el reporte.

Estados del hilo:

    iniciar()  ->  CARGANDO  ->  CORRIENDO  <->  PAUSADO
                                     |              |
                                     +--> DETENIDO <+
"""

import time
from contextlib import contextmanager

import cv2
from PySide6.QtCore import QMutex, QThread, QWaitCondition, Signal
from PySide6.QtGui import QImage

from deteccion.vision_pipeline import VisionPipeline, MODE_GAME, MODE_TEST
from evaluacion.metrics_logger import PerformanceMetrics


# Estados que se reportan a la GUI
STATE_LOADING = "CARGANDO"
STATE_RUNNING = "CORRIENDO"
STATE_PAUSED = "PAUSADO"
STATE_STOPPED = "DETENIDO"


class VisionWorker(QThread):

    # Imagen ya procesada (con landmarks / plano dibujados)
    frame_ready = Signal(QImage)

    # FrameResult del pipeline
    result_ready = Signal(object)

    # (fps, latencia_ms)
    stats_ready = Signal(float, float)

    # Uno de los STATE_*
    state_changed = Signal(str)

    # Mensaje de error (ej. no hay cámara)
    error = Signal(str)

    # Estado de las pruebas en modo TEST (dict de get_status())
    test_status = Signal(object)

    # Ruta del reporte generado al detener (modo TEST)
    report_ready = Signal(str)


    def __init__(self, camera_index=0, mode=MODE_GAME, parent=None):

        super().__init__(parent)

        self.camera_index = camera_index

        self._mutex = QMutex()
        self._resume_condition = QWaitCondition()

        self._running = True
        self._paused = False
        self._requested_mode = mode

        # Órdenes de prueba pendientes: ("start", gesto) / ("cancel", None)
        self._test_commands = []


    @contextmanager
    def _locked(self):
        # lock()/unlock() explícitos: el "with QMutexLocker(...)"
        # de algunas versiones de PySide6 tiene un error de
        # conteo de referencias que puede tumbar el programa
        self._mutex.lock()
        try:
            yield
        finally:
            self._mutex.unlock()


    # =============================================
    # CONTROLES (se llaman desde el hilo de la GUI)
    # =============================================

    def pause(self):
        with self._locked():
            self._paused = True


    def resume(self):
        with self._locked():
            self._paused = False
            # Despierta al hilo que está esperando
            self._resume_condition.wakeAll()


    def stop(self):
        with self._locked():
            self._running = False
            self._paused = False
            self._resume_condition.wakeAll()


    def set_mode(self, mode):
        with self._locked():
            self._requested_mode = mode


    def start_trial(self, gesture):
        """Pide iniciar la prueba de un gesto (solo en modo TEST)."""
        with self._locked():
            self._test_commands.append(("start", gesture))


    def cancel_trial(self):
        """Pide cancelar la prueba en curso."""
        with self._locked():
            self._test_commands.append(("cancel", None))


    # =============================================
    # BUCLE DEL HILO
    # =============================================

    def run(self):

        self.state_changed.emit(STATE_LOADING)

        cap = cv2.VideoCapture(self.camera_index)

        if not cap.isOpened():
            self.error.emit(f"No se pudo abrir la cámara {self.camera_index}")
            self.state_changed.emit(STATE_STOPPED)
            return

        # MediaPipe se crea DENTRO del hilo que lo usa
        try:
            pipeline = VisionPipeline()
        except Exception as error:
            cap.release()
            self.error.emit(f"No se pudieron cargar los modelos: {error}")
            self.state_changed.emit(STATE_STOPPED)
            return

        # Métricas del modo TEST (solo se usan en este hilo)
        metrics = PerformanceMetrics(
            output_dir="metrics",
            trial_timeout=6.0,   # segundos para hacer el gesto
            countdown=3.0,       # cuenta regresiva antes de cada prueba
            start_active=False,
        )
        metrics.set_info(
            resolucion_camara=(
                f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
            )
        )

        mode = None   # se aplica el modo pedido en la primera vuelta

        self.state_changed.emit(STATE_RUNNING)

        fps = 0.0
        previous_time = time.perf_counter()

        try:
            while True:

                # -----------------------------
                # PAUSA / DETENER
                # -----------------------------

                with self._locked():

                    if self._paused and self._running:
                        self.state_changed.emit(STATE_PAUSED)

                        # En TEST se pausan las métricas: una prueba
                        # en curso se cancela y el tiempo en pausa
                        # no cuenta como un frame lento
                        if mode == MODE_TEST:
                            metrics.pause()
                            self.test_status.emit(metrics.get_status())

                        # El hilo se BLOQUEA aquí sin consumir CPU
                        # hasta que resume() o stop() lo despierten
                        while self._paused and self._running:
                            self._resume_condition.wait(self._mutex)

                        if self._running:
                            if mode == MODE_TEST:
                                metrics.resume()
                            self.state_changed.emit(STATE_RUNNING)
                            previous_time = time.perf_counter()

                    if not self._running:
                        break

                    requested_mode = self._requested_mode
                    commands = self._test_commands
                    self._test_commands = []

                # -----------------------------
                # CAMBIO DE MODO
                # -----------------------------

                if requested_mode != mode:

                    # Las métricas solo corren en TEST
                    if mode == MODE_TEST:
                        metrics.pause()
                    if requested_mode == MODE_TEST:
                        metrics.resume()

                    pipeline.set_mode(requested_mode)
                    mode = requested_mode

                    if mode == MODE_TEST:
                        self.test_status.emit(metrics.get_status())

                # -----------------------------
                # ÓRDENES DE PRUEBA (botones)
                # -----------------------------

                for command, gesture in commands:
                    if mode != MODE_TEST:
                        continue
                    if command == "start":
                        metrics.start_trial(gesture)
                    else:
                        metrics.cancel_trial()

                # -----------------------------
                # CAPTURA + PROCESAMIENTO
                # -----------------------------

                ret, frame = cap.read()

                if not ret:
                    self.error.emit("Se perdió la señal de la cámara")
                    break

                in_test = mode == MODE_TEST

                if in_test:
                    metrics.begin_frame()

                # Imagen en espejo (como selfie)
                frame = cv2.flip(frame, 1)

                # El panel de texto lo muestra la GUI,
                # no se dibuja sobre el video
                result = pipeline.process(
                    frame,
                    measure=metrics.measure if in_test else None,
                    draw_panel=False,
                )

                if in_test:
                    metrics.end_frame(result.gesture, result.person_detected)

                # -----------------------------
                # FPS (promedio móvil)
                # -----------------------------

                now = time.perf_counter()
                dt = now - previous_time
                previous_time = now

                if dt > 0:
                    fps = 1 / dt if fps == 0 else 0.9 * fps + 0.1 * (1 / dt)

                # -----------------------------
                # ENVIAR A LA GUI
                # -----------------------------

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channels = rgb.shape

                # .copy(): la QImage debe tener sus propios datos
                # porque el arreglo de NumPy se reutiliza
                image = QImage(
                    rgb.data, width, height, channels * width,
                    QImage.Format.Format_RGB888,
                ).copy()

                self.frame_ready.emit(image)
                self.result_ready.emit(result)
                self.stats_ready.emit(fps, result.processing_ms)

                if in_test:
                    self.test_status.emit(metrics.get_status())

        finally:
            cap.release()
            pipeline.close()

            # Guardar métricas y reporte si se usó el modo TEST
            # (en este hilo: la GUI no se congela mientras tanto)
            if metrics.frame_count > 0:
                try:
                    metrics.pause()
                    json_path = metrics.save()

                    from evaluacion.generate_report import generate
                    generate(json_path)

                    self.report_ready.emit(json_path)
                except Exception as error:
                    self.error.emit(f"No se pudo guardar el reporte: {error}")

            self.state_changed.emit(STATE_STOPPED)
