import cv2
import time

from pose_detector import PoseDetector
from hand_detector import HandDetector
from gesture_detector import GestureDetector


# -----------------------------
# CONFIGURACIÓN DE MEDIAPIPE
# -----------------------------

# Crear detector de postura
pose_detector = PoseDetector()

# Crear detector de manos
hand_detector = HandDetector()

# Crear detector de gestos
gesture_detector = GestureDetector()


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

# Tiempo hasta el que se mostrará
# el último gesto dinámico detectado
reload_display_until = 0
start_display_until = 0
end_display_until = 0

while True:

    ret, frame = cap.read()

    if not ret:
        print("Error: No se pudo capturar el frame")
        break

    # OpenCV trabaja en BGR
    # MediaPipe trabaja en RGB
    frame_rgb = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )

    # -----------------------------
    # DETECCIÓN CON MEDIAPIPE
    # -----------------------------

    # Analizar postura
    pose_result = pose_detector.detect(
        frame_rgb,
        frame_timestamp_ms
    )

    # Analizar manos
    hand_result = hand_detector.detect(
        frame_rgb,
        frame_timestamp_ms
    )

    # Aumentar timestamp después de analizar
    # postura y manos en el mismo frame
    frame_timestamp_ms += 33

    # -----------------------------
    # DIBUJAR LANDMARKS
    # -----------------------------

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

    # -----------------------------
    # DETECCIÓN DE GESTOS
    # -----------------------------

    # ESCUDO
    shield_detected = gesture_detector.detect_shield(
        pose_result
    )

    # Geometría corporal de ATAQUE
    attack_body_detected = (
        gesture_detector.detect_attack_body(
            pose_result
        )
    )

    # Comprobar que las dos manos
    # estén haciendo forma de pistola
    gun_hands_detected = (
        hand_detector.detect_gun_hands(
            hand_result
        )
    )

    # ATAQUE solamente es válido si
    # se cumplen cuerpo + dos pistolas
    attack_detected = (
        attack_body_detected
        and gun_hands_detected
    )

    # RECARGAR
    reload_detected = gesture_detector.detect_reload(
        pose_result
    )

    # Si se completó la recarga,
    # mantener el mensaje visible durante 0.8 segundos
    if reload_detected:
        reload_display_until = time.time() + 0.8

    # INICIO
    start_detected = gesture_detector.detect_start(
        pose_result
    )

    # Mantener INICIO visible brevemente
    # después de completar las tres palmadas
    if start_detected:
        start_display_until = time.time() + 0.8

    # FIN
    end_detected = gesture_detector.detect_end(
        pose_result
    )

    if end_detected:
        end_display_until = time.time() + 0.8

    # -----------------------------
    # POSTURA DETECTADA
    # -----------------------------
    detected_gesture = "---"

    # -----------------------------
    # POSTURAS ESTÁTICAS
    # -----------------------------

    if shield_detected:
        detected_gesture = "ESCUDO"

    elif attack_detected:
        detected_gesture = "ATAQUE"

    # -----------------------------
    # POSTURAS DINÁMICAS
    # -----------------------------

    elif time.time() < reload_display_until:
        detected_gesture = "RECARGAR"

    elif time.time() < start_display_until:
        detected_gesture = "INICIO"

    elif time.time() < end_display_until:
        detected_gesture = "FIN"

    # Mostrar postura actual
    cv2.putText(
        frame,
        f"Postura: {detected_gesture}",
        (30, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 255),
        2
    )

    # -----------------------------
    # ESTADO DE DETECCIÓN
    # -----------------------------

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

    # -----------------------------
    # CALCULAR FPS
    # -----------------------------

    current_time = time.time()

    time_difference = (
        current_time - previous_time
    )

    if time_difference > 0:
        fps = 1 / time_difference
    else:
        fps = 0

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

    # -----------------------------
    # MOSTRAR RESULTADO
    # -----------------------------

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