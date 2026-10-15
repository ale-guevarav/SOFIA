import os
import cv2
import time

# Trabajar siempre desde la carpeta de este archivo,
# para que las rutas "models/..." y "metrics/..." funcionen
# sin importar desde dónde se ejecute (ej. botón ▶ de VS Code)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from pose_detector import PoseDetector
from hand_detector import HandDetector
from gesture_detector import GestureDetector
from smoothing import TemporalConfirmation
from metrics_logger import PerformanceMetrics
from hand_tracker import HandTracker


# =============================================
# MODOS DEL SISTEMA
# =============================================
#
#   JUEGO     -> Reconoce las 5 posturas (uso normal).
#   TEST      -> Igual que JUEGO + pruebas y métricas (teclas 1-5, 0, s).
#   TRACKING  -> NO reconoce posturas. Solo sigue la mano y la
#                ubica en un plano cartesiano con (0,0) al centro.
#
# Teclas para cambiar de modo:
#   J = JUEGO   T = TEST   K = TRACKING   M = siguiente modo
#   Q = salir

MODE_GAME = "JUEGO"
MODE_TEST = "TEST"
MODE_TRACKING = "TRACKING"

MODES = [MODE_GAME, MODE_TEST, MODE_TRACKING]

MODE_KEYS = {
    ord("j"): MODE_GAME,
    ord("t"): MODE_TEST,
    ord("k"): MODE_TRACKING,
}

NEXT_MODE_KEY = ord("m")

# Colores BGR de la etiqueta de cada modo
MODE_COLORS = {
    MODE_GAME: (0, 200, 0),
    MODE_TEST: (0, 0, 255),
    MODE_TRACKING: (255, 160, 0),
}

# Modo con el que arranca el programa
INITIAL_MODE = MODE_GAME


# =============================================
# RECONOCIMIENTO DE POSTURAS
# =============================================

class GestureRecognition:
    """
    Agrupa la lógica de reconocimiento de posturas
    para poder reiniciarla al cambiar de modo.
    """

    def __init__(self, hand_detector):

        self.hand_detector = hand_detector
        self.reset()


    def reset(self):

        # Detector nuevo = estados internos limpios
        # (palmadas, recarga, saludo, etc.)
        self.gesture_detector = GestureDetector()

        # -----------------------------
        # CONFIRMACIÓN TEMPORAL
        # -----------------------------

        self.shield_confirmation = TemporalConfirmation(
            required_frames=5
        )

        self.attack_confirmation = TemporalConfirmation(
            required_frames=5
        )

        # RECARGAR ahora es postura estática
        self.reload_confirmation = TemporalConfirmation(
            required_frames=5
        )

        # Tiempo hasta el que se mostrará
        # el último gesto dinámico detectado
        self.start_display_until = 0
        self.end_display_until = 0


    def update(self, smoothed_landmarks, hand_result):
        """Regresa el nombre de la postura detectada o '---'."""

        now = time.time()

        # -----------------------------
        # ESCUDO
        # -----------------------------

        shield_raw = (
            self.gesture_detector.detect_shield(
                smoothed_landmarks
            )
        )

        shield_detected = (
            self.shield_confirmation.update(
                shield_raw
            )
        )

        # -----------------------------
        # ATAQUE: cuerpo + dos pistolas
        # -----------------------------

        attack_body_detected = (
            self.gesture_detector.detect_attack_body(
                smoothed_landmarks
            )
        )

        gun_hands_detected = (
            self.hand_detector.detect_gun_hands(
                hand_result
            )
        )

        attack_detected = (
            self.attack_confirmation.update(
                attack_body_detected
                and gun_hands_detected
            )
        )

        # -----------------------------
        # RECARGAR - POSTURA ESTÁTICA
        # -----------------------------

        reload_body_detected = (
            self.gesture_detector.detect_reload(
                smoothed_landmarks
            )
        )

        # Si ambas manos forman pistolas,
        # no permitir RECARGAR (es ATAQUE)
        reload_detected = (
            self.reload_confirmation.update(
                reload_body_detected
                and not gun_hands_detected
            )
        )

        # -----------------------------
        # INICIO
        # -----------------------------

        if self.gesture_detector.detect_start(smoothed_landmarks):
            self.start_display_until = now + 0.8

        # -----------------------------
        # FIN
        # -----------------------------

        if self.gesture_detector.detect_end(smoothed_landmarks):
            self.end_display_until = now + 0.8

        # -----------------------------
        # POSTURA DETECTADA
        # -----------------------------

        # POSTURAS ESTÁTICAS
        if shield_detected:
            return "ESCUDO"

        if attack_detected:
            return "ATAQUE"

        if reload_detected:
            return "RECARGAR"

        # POSTURAS DINÁMICAS
        if now < self.start_display_until:
            return "INICIO"

        if now < self.end_display_until:
            return "FIN"

        return "---"


# =============================================
# TEXTOS DE INTERFAZ
# =============================================

def put_text(frame, text, position, color, scale=0.8, thickness=2,
             outline=True):

    # Contorno negro para que se lea sobre cualquier fondo
    if outline:
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (0, 0, 0), thickness + 3, cv2.LINE_AA)

    cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thickness, cv2.LINE_AA)


def draw_mode_label(frame, mode):

    width = frame.shape[1]

    label = f"MODO: {mode}"
    help_text = "[J]uego [T]est [K]tracking [M]cambiar [Q]salir"

    (label_width, _), _ = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2
    )
    (help_width, _), _ = cv2.getTextSize(
        help_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
    )

    put_text(frame, label, (width - label_width - 20, 40),
             MODE_COLORS[mode], 0.9, 2)

    # Menú: texto limpio sobre una franja oscura
    # semitransparente (sin contorno)
    help_x = width - help_width - 20
    help_y = 68

    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (help_x - 8, help_y - 16),
        (width - 12, help_y + 8),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

    put_text(frame, help_text, (help_x, help_y),
             (255, 255, 255), 0.45, 1, outline=False)


# =============================================
# CONFIGURACIÓN
# =============================================

# -----------------------------
# MEDIAPIPE
# -----------------------------

pose_detector = PoseDetector()
hand_detector = HandDetector()

gesture_recognition = GestureRecognition(hand_detector)

hand_tracker = HandTracker(alpha=0.5)


# -----------------------------
# REGISTRO DE MÉTRICAS
# -----------------------------

# Arranca en pausa: solo mide en modo TEST
metrics = PerformanceMetrics(
    output_dir="metrics",
    trial_timeout=6.0,   # segundos para hacer el gesto
    countdown=3.0,       # cuenta regresiva antes de cada prueba
    start_active=False,
)


# -----------------------------
# CÁMARA
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
print("Modos: J juego | T test | K tracking | M siguiente | Q salir")
print("En TEST: 1-5 probar gesto | 0 modo libre | s guardar")


# =============================================
# CAMBIO DE MODO
# =============================================

mode = INITIAL_MODE

if mode == MODE_TEST:
    metrics.resume()


def change_mode(current_mode, new_mode):

    if new_mode == current_mode:
        return current_mode

    # -----------------------------
    # SALIR DEL MODO ACTUAL
    # -----------------------------

    if current_mode == MODE_TEST:
        metrics.pause()

    # -----------------------------
    # ENTRAR AL NUEVO MODO
    # -----------------------------

    if new_mode == MODE_TEST:
        metrics.resume()

    if new_mode == MODE_TRACKING:
        hand_tracker.reset()

    # Al volver de TRACKING, los landmarks del cuerpo
    # y los gestos dinámicos tienen datos viejos:
    # se reinician para evitar detecciones falsas
    if current_mode == MODE_TRACKING:
        pose_detector.smoother.reset()
        gesture_recognition.reset()

    print(f"[MODO] {current_mode} -> {new_mode}")

    return new_mode


# =============================================
# WHILE PRINCIPAL
# =============================================

# MediaPipe (timestamp creciente)
frame_timestamp_ms = 0

previous_time = time.time()

# Última información de tracking
# (lista de HandPosition, disponible para usarla después)
hand_positions = []

try:

    while True:

        ret, frame = cap.read()

        if not ret:
            print("Error: No se pudo capturar el frame")
            break

        # Empieza a medir el procesamiento
        # (solo hace algo en modo TEST)
        metrics.begin_frame()

        # OpenCV trabaja en BGR
        # MediaPipe trabaja en RGB
        frame_rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        # =============================================
        # MODO TRACKING
        # =============================================

        if mode == MODE_TRACKING:

            # Solo manos: NO se analiza la postura
            # ni se reconocen gestos
            hand_result = hand_detector.detect(
                frame_rgb,
                frame_timestamp_ms
            )

            frame_timestamp_ms += 33

            # Posición de cada mano en el plano cartesiano
            hand_positions = hand_tracker.update(
                hand_result,
                frame.shape
            )

            # Plano -> esqueleto de la mano -> vectores
            hand_tracker.draw_plane(frame)

            hand_detector.draw(
                frame,
                hand_result
            )

            hand_tracker.draw_positions(
                frame,
                hand_positions
            )

        # =============================================
        # MODOS JUEGO Y TEST
        # =============================================

        else:

            # -----------------------------
            # DETECCIÓN CON MEDIAPIPE
            # -----------------------------

            with metrics.measure("pose"):

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

                detected_gesture = gesture_recognition.update(
                    smoothed_landmarks,
                    hand_result
                )

            # -----------------------------
            # TEXTOS EN PANTALLA
            # -----------------------------

            with metrics.measure("dibujo"):

                put_text(
                    frame,
                    f"Postura: {detected_gesture}",
                    (30, 130),
                    (0, 255, 255),
                    0.9
                )

                if person_detected:
                    put_text(frame, "Persona detectada",
                             (30, 50), (0, 255, 0), 1)
                else:
                    put_text(frame, "Persona no detectada",
                             (30, 50), (0, 0, 255), 1)

            # -----------------------------
            # MÉTRICAS (solo TEST)
            # -----------------------------

            if mode == MODE_TEST:

                metrics.end_frame(
                    detected_gesture,
                    person_detected
                )

                metrics.draw_overlay(frame)

        # =============================================
        # COMÚN A TODOS LOS MODOS
        # =============================================

        # -----------------------------
        # FPS
        # -----------------------------

        current_time = time.time()
        time_difference = current_time - previous_time
        fps = 1 / time_difference if time_difference > 0 else 0
        previous_time = current_time

        put_text(
            frame,
            f"FPS: {int(fps)}",
            (30, 90),
            (255, 255, 255),
            0.8
        )

        draw_mode_label(frame, mode)

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

        # Cambiar de modo
        if key in MODE_KEYS:
            mode = change_mode(mode, MODE_KEYS[key])

        elif key == NEXT_MODE_KEY:
            next_mode = MODES[(MODES.index(mode) + 1) % len(MODES)]
            mode = change_mode(mode, next_mode)

        # Teclas de pruebas (1-5, 0, x, s) solo en TEST
        elif mode == MODE_TEST:
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

    # Solo si se usó el modo TEST
    if metrics.frame_count > 0:

        metrics.pause()
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
