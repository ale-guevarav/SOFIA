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

    def get_finger_distances(self, result):

        measurements = []

        if not result.hand_landmarks:
            return measurements

        for hand_landmarks in result.hand_landmarks:

            wrist = hand_landmarks[0]

            thumb_tip = hand_landmarks[4]
            index_tip = hand_landmarks[8]
            middle_tip = hand_landmarks[12]
            ring_tip = hand_landmarks[16]
            pinky_tip = hand_landmarks[20]

            # Punto de referencia para calcular
            # el tamaño aproximado de la mano
            middle_mcp = hand_landmarks[9]

            # -----------------------------
            # FUNCIÓN DE DISTANCIA 3D
            # -----------------------------

            def distance_3d(point_a, point_b):

                return (
                    (point_a.x - point_b.x) ** 2
                    + (point_a.y - point_b.y) ** 2
                    + (point_a.z - point_b.z) ** 2
                ) ** 0.5

            # -----------------------------
            # TAMAÑO DE REFERENCIA
            # -----------------------------

            hand_size = distance_3d(
                wrist,
                middle_mcp
            )

            if hand_size == 0:
                continue

            # -----------------------------
            # DISTANCIAS NORMALIZADAS
            # -----------------------------

            thumb_distance = (
                distance_3d(thumb_tip, wrist)
                / hand_size
            )

            index_distance = (
                distance_3d(index_tip, wrist)
                / hand_size
            )

            middle_distance = (
                distance_3d(middle_tip, wrist)
                / hand_size
            )

            ring_distance = (
                distance_3d(ring_tip, wrist)
                / hand_size
            )

            pinky_distance = (
                distance_3d(pinky_tip, wrist)
                / hand_size
            )

            measurements.append({
                "thumb": thumb_distance,
                "index": index_distance,
                "middle": middle_distance,
                "ring": ring_distance,
                "pinky": pinky_distance
            })

        return measurements

    def detect_gun_hands(self, result):

        # Obtener las distancias normalizadas
        measurements = self.get_finger_distances(
            result
        )

        # ATAQUE requiere exactamente dos manos detectadas
        if len(measurements) < 2:
            return False

        gun_hands = 0

        # Analizar cada mano
        for hand in measurements:

            # Pulgar e índice deben estar extendidos
            thumb_extended = (
                hand["thumb"] > 1.40
            )

            index_extended = (
                hand["index"] > 1.40
            )

            # Los otros tres dedos deben estar recogidos
            middle_folded = (
                hand["middle"] < 1.00
            )

            ring_folded = (
                hand["ring"] < 1.00
            )

            pinky_folded = (
                hand["pinky"] < 1.00
            )

            # Comprobar forma de pistola
            gun_shape = (
                thumb_extended
                and index_extended
                and middle_folded
                and ring_folded
                and pinky_folded
            )

            if gun_shape:
                gun_hands += 1

        # Las DOS manos deben formar pistola
        return gun_hands >= 2

    def close(self):
        self.detector.close()