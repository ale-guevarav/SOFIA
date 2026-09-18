import cv2
import time

from pose_detector import PoseDetector
from hand_detector import HandDetector


# -----------------------------
# CONFIGURACIÓN DE MEDIAPIPE
# -----------------------------

# Crear detector de postura
pose_detector = PoseDetector()

# Crear detector de manos
hand_detector = HandDetector()


# -----------------------------
# CONFIGURACIÓN DE LA CÁMARA
# -----------------------------

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: No se pudo abrir la cámara")
    pose_detector.close()
    hand_detector.close()
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
    frame_rgb = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )

    # Analizar la postura
    pose_result = pose_detector.detect(
        frame_rgb,
        frame_timestamp_ms
    )

    # Analizar las manos
    hand_result = hand_detector.detect(
        frame_rgb,
        frame_timestamp_ms
    )

    # Aumentar timestamp después de analizar
    # postura y manos en el mismo frame
    frame_timestamp_ms += 33

    # Dibujar postura
    person_detected = pose_detector.draw(
        frame,
        pose_result
    )

    # Dibujar manos
    hand_detector.draw(
        frame,
        hand_result
    )

    # Mostrar estado de detección
    if person_detected:

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

pose_detector.close()
hand_detector.close()