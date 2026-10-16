"""
PIPELINE DE VISIÓN - SOFIA

Procesa UN frame de la cámara según el modo activo y regresa
el resultado. Es el "motor" que comparten:

    - main.py      -> ventana de OpenCV con teclado (y métricas)
    - la GUI       -> vision_worker.py lo ejecuta en un hilo

Modos:
    JUEGO     -> Pose + Manos + reconocimiento de las 5 posturas.
    TEST      -> Igual que JUEGO (main.py agrega las métricas).
    TRACKING  -> NO reconoce posturas. Solo sigue la mano y la
                 ubica en el plano cartesiano. Pose solo se usa
                 como respaldo cuando la mano se pierde.
"""

import time
from contextlib import nullcontext
from dataclasses import dataclass, field

import cv2

from .pose_detector import PoseDetector
from .hand_detector import HandDetector
from .hand_tracker import HandTracker
from .gesture_recognition import GestureRecognition, NO_GESTURE


# -----------------------------
# MODOS
# -----------------------------

MODE_GAME = "JUEGO"
MODE_TEST = "TEST"
MODE_TRACKING = "TRACKING"

MODES = [MODE_GAME, MODE_TEST, MODE_TRACKING]


# -----------------------------
# RESULTADO DE UN FRAME
# -----------------------------

@dataclass
class FrameResult:

    mode: str

    # Postura detectada (JUEGO / TEST) o "---"
    gesture: str = NO_GESTURE

    # Si Pose detectó a una persona (JUEGO / TEST)
    person_detected: bool = False

    # Manos en el plano cartesiano (TRACKING)
    hand_positions: list = field(default_factory=list)

    # Milisegundos que tardó en procesarse el frame
    processing_ms: float = 0.0


def _no_measure(_stage_name):
    return nullcontext()


# =============================================
# PIPELINE
# =============================================

class VisionPipeline:

    def __init__(self, tracking_confidence=0.3):

        # -----------------------------
        # MEDIAPIPE
        # -----------------------------

        self.pose_detector = PoseDetector()

        # Detector de manos para JUEGO / TEST
        # (umbrales normales, evita falsos ATAQUE)
        self.hand_detector = HandDetector()

        # Detector de manos para TRACKING con umbrales
        # más bajos: no pierde la mano tan fácil cuando
        # la palma se inclina
        self.tracking_hand_detector = HandDetector(
            min_detection_confidence=tracking_confidence,
            min_presence_confidence=tracking_confidence,
            min_tracking_confidence=tracking_confidence,
        )

        # -----------------------------
        # LÓGICA
        # -----------------------------

        self.gesture_recognition = GestureRecognition(self.hand_detector)
        self.hand_tracker = HandTracker()

        self.mode = MODE_GAME

        self._last_timestamp_ms = -1


    # =============================================
    # CAMBIO DE MODO
    # =============================================

    def set_mode(self, new_mode):

        if new_mode not in MODES:
            raise ValueError(f"Modo desconocido: {new_mode}")

        if new_mode == self.mode:
            return

        if new_mode == MODE_TRACKING:
            self.hand_tracker.reset()

        # Al volver de TRACKING, los landmarks del cuerpo
        # y los gestos dinámicos tienen datos viejos:
        # se reinician para evitar detecciones falsas
        if self.mode == MODE_TRACKING:
            self.pose_detector.smoother.reset()
            self.gesture_recognition.reset()

        self.mode = new_mode


    # =============================================
    # TIMESTAMP PARA MEDIAPIPE
    # =============================================

    def _next_timestamp(self):

        # MediaPipe (modo VIDEO) exige timestamps
        # estrictamente crecientes en milisegundos
        timestamp_ms = int(time.monotonic() * 1000)

        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1

        self._last_timestamp_ms = timestamp_ms

        return timestamp_ms


    # =============================================
    # PROCESAR UN FRAME
    # =============================================

    def process(self, frame, measure=None, draw=True, draw_panel=True):
        """
        Procesa un frame BGR (lo modifica dibujando encima
        si draw=True) y regresa un FrameResult.

        measure: función opcional measure(nombre_etapa) que
        regresa un context manager (ej. metrics.measure) para
        medir cuánto tarda cada etapa.
        """

        measure = measure or _no_measure
        start = time.perf_counter()

        # OpenCV trabaja en BGR
        # MediaPipe trabaja en RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        timestamp_ms = self._next_timestamp()

        if self.mode == MODE_TRACKING:
            result = self._process_tracking(
                frame, frame_rgb, timestamp_ms, measure, draw, draw_panel
            )
        else:
            result = self._process_game(
                frame, frame_rgb, timestamp_ms, measure, draw
            )

        result.processing_ms = (time.perf_counter() - start) * 1000

        return result


    # -----------------------------
    # TRACKING
    # -----------------------------

    def _process_tracking(self, frame, frame_rgb, timestamp_ms, measure, draw, draw_panel):

        with measure("manos"):
            hand_result = self.tracking_hand_detector.detect(
                frame_rgb,
                timestamp_ms
            )

        # Pose solo se ejecuta si se perdió una mano
        # que se venía siguiendo (respaldo)
        pose_result = None

        if self.hand_tracker.needs_pose_fallback(hand_result):
            with measure("pose"):
                pose_result = self.pose_detector.detect(
                    frame_rgb,
                    timestamp_ms
                )

        hand_positions = self.hand_tracker.update(
            hand_result,
            frame.shape,
            pose_result=pose_result,
        )

        if draw:
            with measure("dibujo"):
                # Plano -> esqueleto de la mano -> vectores
                self.hand_tracker.draw_plane(frame)
                self.tracking_hand_detector.draw(frame, hand_result)
                self.hand_tracker.draw_positions(
                    frame, hand_positions, panel=draw_panel
                )

        return FrameResult(
            mode=self.mode,
            hand_positions=hand_positions,
        )


    # -----------------------------
    # JUEGO / TEST
    # -----------------------------

    def _process_game(self, frame, frame_rgb, timestamp_ms, measure, draw):

        with measure("pose"):

            pose_result = self.pose_detector.detect(
                frame_rgb,
                timestamp_ms
            )

            # Aplicar EMA a los landmarks corporales
            smoothed_landmarks = self.pose_detector.get_smoothed_landmarks(
                pose_result
            )

        with measure("manos"):

            hand_result = self.hand_detector.detect(
                frame_rgb,
                timestamp_ms
            )

        person_detected = bool(pose_result.pose_landmarks)

        if draw:
            with measure("dibujo"):
                self.pose_detector.draw(frame, pose_result)
                self.hand_detector.draw(frame, hand_result)

        with measure("gestos"):
            gesture = self.gesture_recognition.update(
                smoothed_landmarks,
                hand_result
            )

        return FrameResult(
            mode=self.mode,
            gesture=gesture,
            person_detected=person_detected,
        )


    # =============================================
    # LIBERAR RECURSOS
    # =============================================

    def close(self):

        self.pose_detector.close()
        self.hand_detector.close()
        self.tracking_hand_detector.close()
