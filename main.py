import cv2
import time

from pose_detector import PoseDetector
from hand_detector import HandDetector
from gesture_detector import GestureDetector
from smoothing import TemporalConfirmation
from metrics_logger import PerformanceMetrics


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
# CONFIRMACIÓN TEMPORAL
# -----------------------------

shield_confirmation = TemporalConfirmation(
    required_frames=5
)

attack_confirmation = TemporalConfirmation(
    required_frames=5
)


# -----------------------------
# REGISTRO DE MÉTRICAS
# -----------------------------

metrics = PerformanceMetrics(
    output_dir="metrics",
    trial_timeout=6.0,   # segundos para hacer el gesto
    countdown=3.0,       # cuenta regresiva antes de cada prueba
)


# -----------------------------
# CONFIGURACIÓN DE LA CÁMARA
# -----------------------------

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: No se pudo abrir la cámara")
    pose_detector.close()
    hand_detector.close()
    exit()

metrics.set_info(
    resolucion_camara=(
        f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
        f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
    )
)

print("Cámara iniciada correctamente")
print("Presiona 'q' para cerrar")
print("Métricas: 1-5 probar gesto | 0 modo libre | s guardar")


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

try:

    while True:

        ret, frame = cap.read()

        if not ret:
            print("Error: No se pudo capturar el frame")
            break

        # Empieza a medir el procesamiento
        # (no incluye la espera de la cámara)
        metrics.begin_frame()

        # -----------------------------
        # DETECCIÓN CON MEDIAPIPE
        # -----------------------------

        with metrics.measure("pose"):

            # OpenCV trabaja en BGR
            # MediaPipe trabaja en RGB
            frame_rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            # Analizar postura
            pose_result = pose_detector.detect(
                frame_rgb,
                frame_timestamp_ms
            )

            # Aplicar EMA a los landmarks corporales
            smoothed_landmarks = (
                pose_detector.get_smoothed_landmarks(
                    pose_result
                )
            )

        with metrics.measure("manos"):

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

        with metrics.measure("dibujo"):

            person_detected = pose_detector.draw(
                frame,
                pose_result
            )

            hand_detector.draw(
                frame,
                hand_result
            )


        # -----------------------------
        # DETECCIÓN DE GESTOS
        # -----------------------------

        with metrics.measure("gestos"):

            # ESCUDO
            shield_raw = (
                gesture_detector.detect_shield(
                    smoothed_landmarks
                )
            )

            shield_detected = (
                shield_confirmation.update(
                    shield_raw
                )
            )

            # ATAQUE: cuerpo + dos pistolas
            attack_body_detected = (
                gesture_detector.detect_attack_body(
                    smoothed_landmarks
                )
            )

            gun_hands_detected = (
                hand_detector.detect_gun_hands(
                    hand_result
                )
            )

            attack_raw = (
                attack_body_detected
                and gun_hands_detected
            )

            attack_detected = (
                attack_confirmation.update(
                    attack_raw
                )
            )

            # RECARGAR
            reload_detected = (
                gesture_detector.detect_reload(
                    smoothed_landmarks
                )
            )

            if reload_detected:
                reload_display_until = (
                    time.time() + 0.8
                )

            # INICIO
            start_detected = (
                gesture_detector.detect_start(
                    smoothed_landmarks
                )
            )

            if start_detected:
                start_display_until = (
                    time.time() + 0.8
                )

            # FIN
            end_detected = (
                gesture_detector.detect_end(
                    smoothed_landmarks
                )
            )

            if end_detected:
                end_display_until = (
                    time.time() + 0.8
                )

            # -----------------------------
            # POSTURA DETECTADA
            # -----------------------------

            detected_gesture = "---"

            # POSTURAS ESTÁTICAS
            if shield_detected:
                detected_gesture = "ESCUDO"

            elif attack_detected:
                detected_gesture = "ATAQUE"

            # POSTURAS DINÁMICAS
            elif time.time() < reload_display_until:
                detected_gesture = "RECARGAR"

            elif time.time() < start_display_until:
                detected_gesture = "INICIO"

            elif time.time() < end_display_until:
                detected_gesture = "FIN"


        # -----------------------------
        # TEXTOS EN PANTALLA
        # -----------------------------

        with metrics.measure("dibujo"):

            cv2.putText(
                frame,
                f"Postura: {detected_gesture}",
                (30, 130),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 255),
                2
            )

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

            # FPS instantáneo
            current_time = time.time()
            time_difference = current_time - previous_time
            fps = 1 / time_difference if time_difference > 0 else 0
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
        # REGISTRAR MÉTRICAS DEL FRAME
        # -----------------------------

        metrics.end_frame(
            detected_gesture,
            person_detected
        )

        # Estado de la evaluación en pantalla
        metrics.draw_overlay(frame)


        # -----------------------------
        # MOSTRAR RESULTADO
        # -----------------------------

        cv2.imshow(
            "SOFIA - Deteccion de Posturas",
            frame
        )

        key = cv2.waitKey(1) & 0xFF

        # Q para salir
        if key == ord("q"):
            break

        # Teclas de evaluación (1-5, 0, x, s)
        metrics.handle_key(key)

finally:

    # -----------------------------
    # LIBERAR RECURSOS
    # -----------------------------

    cap.release()
    cv2.destroyAllWindows()

    pose_detector.close()
    hand_detector.close()

    # -----------------------------
    # GUARDAR MÉTRICAS Y REPORTE
    # -----------------------------

    json_path = metrics.save()

    try:
        from generate_report import generate
        generate(json_path)
    except Exception as error:
        print(
            "No se pudo generar el reporte automáticamente: "
            f"{error}"
        )
        print("Puedes generarlo con: python generate_report.py")