import cv2
import mediapipe as mp

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from hand_connections import HAND_CONNECTIONS


class HandDetector:
    def __init__(self, model_path="models/hand_landmarker.task"):
        base_options = python.BaseOptions(
            model_asset_path=model_path
        )

        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )

        self.detector = vision.HandLandmarker.create_from_options(options)

    def detect(self, frame_rgb, timestamp_ms):
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=frame_rgb
        )

        return self.detector.detect_for_video(
            mp_image,
            timestamp_ms
        )

    def draw(self, frame, result):
        if not result.hand_landmarks:
            return

        height, width, _ = frame.shape

        for hand_landmarks in result.hand_landmarks:

            # Dibujar conexiones
            for start_idx, end_idx in HAND_CONNECTIONS:
                start = hand_landmarks[start_idx]
                end = hand_landmarks[end_idx]

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
                    (255, 255, 0),
                    2
                )

            # Dibujar los 21 landmarks
            for landmark in hand_landmarks:
                x = int(landmark.x * width)
                y = int(landmark.y * height)

                cv2.circle(
                    frame,
                    (x, y),
                    3,
                    (255, 0, 255),
                    -1
                )

    def close(self):
        self.detector.close()