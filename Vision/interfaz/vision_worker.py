"""
HILO DE PROCESAMIENTO DE VIDEO - SOFIA

QThread que lee la cámara y ejecuta el VisionPipeline FUERA
del hilo de la interfaz. Así la GUI nunca se congela, aunque
MediaPipe tarde varios milisegundos por frame.

Comunicación con la GUI (thread-safe):

    GUI -> hilo:  pause(), resume(), stop(), set_mode()
                  (protegidos con QMutex + QWaitCondition)

    hilo -> GUI:  señales de Qt (frame_ready, result_ready, ...)
                  que Qt entrega en el hilo de la GUI.

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

from deteccion.vision_pipeline import VisionPipeline, MODE_GAME


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


    def __init__(self, camera_index=0, mode=MODE_GAME, parent=None):

        super().__init__(parent)

        self.camera_index = camera_index

        self._mutex = QMutex()
        self._resume_condition = QWaitCondition()

        self._running = True
        self._paused = False
        self._requested_mode = mode


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

                        # El hilo se BLOQUEA aquí sin consumir CPU
                        # hasta que resume() o stop() lo despierten
                        while self._paused and self._running:
                            self._resume_condition.wait(self._mutex)

                        if self._running:
                            self.state_changed.emit(STATE_RUNNING)
                            previous_time = time.perf_counter()

                    if not self._running:
                        break

                    requested_mode = self._requested_mode

                if requested_mode != pipeline.mode:
                    pipeline.set_mode(requested_mode)

                # -----------------------------
                # CAPTURA + PROCESAMIENTO
                # -----------------------------

                ret, frame = cap.read()

                if not ret:
                    self.error.emit("Se perdió la señal de la cámara")
                    break

                # El panel de texto lo muestra la GUI,
                # no se dibuja sobre el video
                result = pipeline.process(frame, draw_panel=False)

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

        finally:
            cap.release()
            pipeline.close()
            self.state_changed.emit(STATE_STOPPED)
