"""
RECONOCIMIENTO DE POSTURAS - SOFIA

Agrupa la lógica que decide qué postura se está haciendo
(ESCUDO, ATAQUE, RECARGAR, INICIO o FIN) a partir de los
landmarks de cuerpo y manos.

Se usa tanto en main.py (ventana de OpenCV) como en la GUI.
"""

import time

from .gesture_detector import GestureDetector
from .smoothing import TemporalConfirmation


NO_GESTURE = "---"

# Identificador numérico de cada postura.
# Es el mismo que usan las teclas de prueba (1-5)
# y el protocolo de comunicación con el ESP32.
GESTURE_IDS = {
    "INICIO": 1,
    "RECARGAR": 2,
    "ESCUDO": 3,
    "ATAQUE": 4,
    "FIN": 5,
}


class GestureRecognition:
    """
    Envuelve GestureDetector + confirmación temporal
    para poder reiniciar todo al cambiar de modo.
    """

    def __init__(self, hand_detector, confirmation_frames=5, dynamic_display_time=0.8):

        self.hand_detector = hand_detector
        self.confirmation_frames = confirmation_frames

        # Tiempo que se mantiene visible un gesto
        # dinámico (INICIO / FIN) después de detectarlo
        self.dynamic_display_time = dynamic_display_time

        self.reset()


    def reset(self):

        # Detector nuevo = estados internos limpios
        # (palmadas, saludo, etc.)
        self.gesture_detector = GestureDetector()

        # -----------------------------
        # CONFIRMACIÓN TEMPORAL
        # -----------------------------

        self.shield_confirmation = TemporalConfirmation(
            required_frames=self.confirmation_frames
        )

        self.attack_confirmation = TemporalConfirmation(
            required_frames=self.confirmation_frames
        )

        # RECARGAR es postura estática
        self.reload_confirmation = TemporalConfirmation(
            required_frames=self.confirmation_frames
        )

        # Tiempo hasta el que se mostrará
        # el último gesto dinámico detectado
        self.start_display_until = 0
        self.end_display_until = 0

        # Posturas que se están viendo en este frame ANTES de la
        # confirmación temporal (para medir el tiempo de reacción
        # y el de reconocimiento en el modo TEST)
        self.candidates = set()


    def update(self, smoothed_landmarks, hand_result):
        """Regresa el nombre de la postura detectada o '---'."""

        now = time.time()

        # -----------------------------
        # ESCUDO
        # -----------------------------

        shield_raw = self.gesture_detector.detect_shield(smoothed_landmarks)

        shield_detected = self.shield_confirmation.update(shield_raw)

        # -----------------------------
        # ATAQUE: cuerpo + dos pistolas
        # -----------------------------

        attack_body_detected = self.gesture_detector.detect_attack_body(
            smoothed_landmarks
        )

        gun_hands_detected = self.hand_detector.detect_gun_hands(
            hand_result
        )

        attack_detected = self.attack_confirmation.update(
            attack_body_detected and gun_hands_detected
        )

        # -----------------------------
        # RECARGAR - POSTURA ESTÁTICA
        # -----------------------------

        # Si ambas manos forman pistolas,
        # no permitir RECARGAR (es ATAQUE)
        reload_raw = (
            self.gesture_detector.detect_reload(smoothed_landmarks)
            and not gun_hands_detected
        )

        reload_detected = self.reload_confirmation.update(reload_raw)

        # -----------------------------
        # INICIO / FIN (dinámicos)
        # -----------------------------

        if self.gesture_detector.detect_start(smoothed_landmarks):
            self.start_display_until = now + self.dynamic_display_time

        if self.gesture_detector.detect_end(smoothed_landmarks):
            self.end_display_until = now + self.dynamic_display_time

        # -----------------------------
        # CANDIDATAS (antes de confirmar)
        # -----------------------------

        # Estáticas: la regla se cumple en este frame.
        # Dinámicas: el movimiento ya empezó (primera palmada
        # para INICIO, mano levantada para FIN).
        candidates = set()

        if shield_raw:
            candidates.add("ESCUDO")
        if attack_body_detected and gun_hands_detected:
            candidates.add("ATAQUE")
        if reload_raw:
            candidates.add("RECARGAR")
        if self.gesture_detector.start_tap_count > 0:
            candidates.add("INICIO")
        if self.gesture_detector.end_active_hand is not None:
            candidates.add("FIN")

        # -----------------------------
        # POSTURA DETECTADA (prioridad)
        # -----------------------------

        gesture = NO_GESTURE

        if shield_detected:
            gesture = "ESCUDO"
        elif attack_detected:
            gesture = "ATAQUE"
        elif reload_detected:
            gesture = "RECARGAR"
        elif now < self.start_display_until:
            gesture = "INICIO"
        elif now < self.end_display_until:
            gesture = "FIN"

        # La postura confirmada también cuenta como candidata
        if gesture != NO_GESTURE:
            candidates.add(gesture)

        self.candidates = candidates

        return gesture
