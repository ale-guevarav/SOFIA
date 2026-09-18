import cv2
import mediapipe as mp
import time

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# -----------------------------
# CONEXIONES ESQUELETO
# -----------------------------

POSE_CONNECTIONS = [
    # Torso
    (11, 12),  # Hombro izquierdo - hombro derecho
    (11, 23),  # Hombro izquierdo - cadera izquierda
    (12, 24),  # Hombro derecho - cadera derecha
    (23, 24),  # Cadera izquierda - cadera derecha

    # Brazo izquierdo
    (11, 13),
    (13, 15),

    # Brazo derecho
    (12, 14),
    (14, 16),

    # Pierna izquierda
    (23, 25),
    (25, 27),

    # Pierna derecha
    (24, 26),
    (26, 28),
]


# -----------------------------
# CONFIGURACIÓN DE MEDIAPIPE
# -----------------------------

MODEL_PATH = "models/pose_landmarker.task"

base_options = python.BaseOptions(
    model_asset_path=MODEL_PATH
)

options = vision.PoseLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_poses=1
)

detector = vision.PoseLandmarker.create_from_options(options)


# -----------------------------
# CONFIGURACIÓN DE LA CÁMARA
# -----------------------------

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: No se pudo abrir la cámara")
    detector.close()
    exit()

print("Cámara iniciada correctamente")
print("Presiona 'q' para cerrar")


# MediaPipe (timestamp creciente)
frame_timestamp_ms = 0


# -----------------------------
# WHILE PRINCIPAL
# -----------------------------
previous_time = time.time()
while True:

    ret, frame = cap.read()

    if not ret:
        print("Error: No se pudo capturar el frame")
        break

    # OpenCV (BGR)
    # MediaPipe (RGB)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Convertir el frame de OpenCV a MediaPipe Image
    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=frame_rgb
    )

    # Analizar la postura
    result = detector.detect_for_video(
        mp_image,
        frame_timestamp_ms
    )

    frame_timestamp_ms += 33

    # Comprobar si MediaPipe detectó una persona
    if result.pose_landmarks:
        landmarks = result.pose_landmarks[0]

        height, width, _ = frame.shape

        # Dibujar conexiones del esqueleto
        for start_idx, end_idx in POSE_CONNECTIONS:

            start = landmarks[start_idx]
            end = landmarks[end_idx]

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

        cv2.putText(
            frame,
            "Persona detectada",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2
        )

    else:

        cv2.putText(
            frame,
            "Persona no detectada",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            2
        )

    # Calcular FPS
    current_time = time.time()

    fps = 1 / (current_time - previous_time)

    previous_time = current_time

    cv2.putText(
        frame,
        f"FPS: {int(fps)}",
        (30, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    # Mostrar resultado
    cv2.imshow(
        "SOFIA - Deteccion de Posturas",
        frame
    )

    # Q para salir
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


# -----------------------------
# LIBERAR RECURSOS
# -----------------------------

cap.release()
cv2.destroyAllWindows()
detector.close()