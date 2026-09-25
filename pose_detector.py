import cv2
import mediapipe as mp

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from pose_connections import POSE_CONNECTIONS


class PoseDetector:

    def __init__(self, model_path="models/pose_landmarker.task"):

        # Configuración de MediaPipe Pose Landmarker
        base_options = python.BaseOptions(
            model_asset_path=model_path
        )

        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1
        )

        self.detector = vision.PoseLandmarker.create_from_options(
            options
        )

    def detect(self, frame_rgb, timestamp_ms):

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

    def draw(self, frame, result):

        # Comprobar si se detectó una persona
        if not result.pose_landmarks:
            return False

        landmarks = result.pose_landmarks[0]

        height, width, _ = frame.shape

        # -----------------------------
        # DIBUJAR ESQUELETO
        # -----------------------------

        # Dibujar conexiones del esqueleto
        for start_idx, end_idx in POSE_CONNECTIONS:

            start = landmarks[start_idx]
            end = landmarks[end_idx]

            # Ignorar conexiones con poca visibilidad
            if start.visibility < 0.5 or end.visibility < 0.5:
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

        # Dibujar los 33 keypoints
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

    def close(self):

        # Liberar recursos de MediaPipe
        self.detector.close()