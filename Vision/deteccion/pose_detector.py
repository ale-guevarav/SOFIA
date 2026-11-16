import os

import cv2
import mediapipe as mp

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from .smoothing import LandmarkSmoother
from .pose_connections import POSE_CONNECTIONS


# -----------------------------
# MODELO
# -----------------------------

# Se usa el primero que exista. El "full" es más preciso que el
# "lite" (sigue mejor los brazos y confunde menos el fondo con una
# persona) a cambio de unos ms más por frame. Se descarga de:
# https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task
POSE_MODELS = (
    "models/pose_landmarker_full.task",
    "models/pose_landmarker.task",        # lite (el que trae el repo)
)

# Umbrales de MediaPipe (por defecto son 0.5). Más altos = menos
# cuerpos inventados en el fondo; presence alto hace que vuelva a
# buscar a la persona en lugar de "seguir" algo que ya no es ella.
MIN_POSE_DETECTION = 0.6
MIN_POSE_PRESENCE = 0.6
MIN_POSE_TRACKING = 0.6

# -----------------------------
# ¿ES DE VERDAD UNA PERSONA?
# -----------------------------

# MediaPipe siempre regresa "su mejor cuerpo", aunque sea una silla o
# alguien al fondo. Se acepta solo si:
#   - la nariz y los dos hombros se ven (visibility >= este valor),
#   - los hombros miden al menos este ancho (fracción del ancho de la
#     imagen; descarta personas lejanas al fondo, ~3.5 m o más),
#   - la cara está arriba y en medio de los hombros (descarta cuerpos
#     armados con la cara de uno y los hombros de otra cosa).
PERSON_MIN_VISIBILITY = 0.6
MIN_SHOULDER_WIDTH = 0.08

NOSE, LEFT_SHOULDER, RIGHT_SHOULDER = 0, 11, 12


def choose_pose_model():
    for path in POSE_MODELS:
        if os.path.exists(path):
            return path
    return POSE_MODELS[-1]


def model_label(path):
    name = os.path.basename(path)
    for kind in ("heavy", "full"):
        if kind in name:
            return kind
    return "lite"


def is_person(landmarks, aspect):
    """
    landmarks: los 33 puntos de Pose (normalizados 0-1).
    aspect: ancho / alto de la imagen (para comparar x con y).
    """

    nose = landmarks[NOSE]
    left = landmarks[LEFT_SHOULDER]
    right = landmarks[RIGHT_SHOULDER]

    if min(nose.visibility, left.visibility, right.visibility) < PERSON_MIN_VISIBILITY:
        return False

    shoulder_width = abs(left.x - right.x)

    if shoulder_width < MIN_SHOULDER_WIDTH:
        return False

    # Cara en medio de los hombros (con margen)
    center_x = (left.x + right.x) / 2
    if abs(nose.x - center_x) > 0.6 * shoulder_width:
        return False

    # Cara arriba de los hombros, a una altura razonable.
    # La diferencia en y se pasa a "unidades de x" con el aspecto.
    head_height = (min(left.y, right.y) - nose.y) / aspect
    if not 0.15 * shoulder_width <= head_height <= 1.5 * shoulder_width:
        return False

    return True


class PoseDetector:

    def __init__(self, model_path=None):

        # -----------------------------
        # CONFIGURACIÓN DE MEDIAPIPE
        # -----------------------------

        self.model_path = model_path or choose_pose_model()
        self.model_name = model_label(self.model_path)

        # ancho / alto del último frame (para is_person)
        self.aspect = 4 / 3

        base_options = python.BaseOptions(
            model_asset_path=self.model_path
        )

        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=MIN_POSE_DETECTION,
            min_pose_presence_confidence=MIN_POSE_PRESENCE,
            min_tracking_confidence=MIN_POSE_TRACKING,
        )

        self.detector = vision.PoseLandmarker.create_from_options(
            options
        )

        # -----------------------------
        # SUAVIZADO DE LANDMARKS
        # -----------------------------

        self.smoother = LandmarkSmoother(
            alpha=0.3
        )


    # =============================================
    # DETECCIÓN DE POSTURA
    # =============================================

    def detect(self, frame_rgb, timestamp_ms):

        height, width = frame_rgb.shape[:2]
        self.aspect = width / height

        # Convertir frame RGB a MediaPipe Image
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=frame_rgb
        )

        # Detectar postura
        return self.detector.detect_for_video(
            mp_image,
            timestamp_ms
        )


    # =============================================
    # LANDMARKS SUAVIZADOS
    # =============================================

    def person_landmarks(self, result):
        """Los landmarks si son de una persona real; si no, None."""

        if not result.pose_landmarks:
            return None

        landmarks = result.pose_landmarks[0]

        return landmarks if is_person(landmarks, self.aspect) else None


    def get_smoothed_landmarks(self, result):

        # Si no hay una persona (o lo detectado no lo parece),
        # reiniciar el filtro
        landmarks = self.person_landmarks(result)

        if landmarks is None:
            self.smoother.reset()
            return None

        # Aplicar EMA a las coordenadas
        return self.smoother.smooth(
            landmarks
        )


    # =============================================
    # DIBUJAR POSTURA
    # =============================================

    def draw(self, frame, result):

        # Solo se dibuja si es una persona real
        # (no cuerpos inventados en el fondo)
        landmarks = self.person_landmarks(result)

        if landmarks is None:
            return False

        height, width, _ = frame.shape

        # -----------------------------
        # DIBUJAR ESQUELETO
        # -----------------------------

        for start_idx, end_idx in POSE_CONNECTIONS:

            start = landmarks[start_idx]
            end = landmarks[end_idx]

            # Ignorar conexiones con poca visibilidad
            if (
                start.visibility < 0.5
                or end.visibility < 0.5
            ):
                continue

            start_point = (
                int(start.x * width),
                int(start.y * height)
            )

            end_point = (
                int(end.x * width),
                int(end.y * height)
            )

            cv2.line(
                frame,
                start_point,
                end_point,
                (0, 255, 0),
                2
            )

        # -----------------------------
        # DIBUJAR KEYPOINTS
        # -----------------------------

        for landmark in landmarks:

            # Ignorar puntos con poca visibilidad
            if landmark.visibility < 0.5:
                continue

            x = int(landmark.x * width)
            y = int(landmark.y * height)

            cv2.circle(
                frame,
                (x, y),
                4,
                (0, 0, 255),
                -1
            )

        return True


    # =============================================
    # LIBERAR RECURSOS
    # =============================================

    def close(self):

        self.detector.close()