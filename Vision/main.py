import os
import cv2
import time

# Trabajar siempre desde la carpeta de este archivo,
# para que las rutas "models/..." y "metrics/..." funcionen
# sin importar desde dónde se ejecute (ej. botón ▶ de VS Code)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from evaluacion.metrics_logger import PerformanceMetrics
from deteccion.vision_pipeline import (
    VisionPipeline,
    MODES,
    MODE_GAME,
    MODE_TEST,
    MODE_TRACKING,
)


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
#
# Toda la detección vive en deteccion/vision_pipeline.py
# (la misma que usa la GUI: gui_app.py).

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

pipeline = VisionPipeline()

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
    pipeline.close()
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

def change_mode(current_mode, new_mode):

    if new_mode == current_mode:
        return current_mode

    # Las métricas solo corren en TEST
    if current_mode == MODE_TEST:
        metrics.pause()

    if new_mode == MODE_TEST:
        metrics.resume()

    pipeline.set_mode(new_mode)

    print(f"[MODO] {current_mode} -> {new_mode}")

    return new_mode


mode = MODE_GAME
mode = change_mode(mode, INITIAL_MODE)


# =============================================
# WHILE PRINCIPAL
# =============================================

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

        # Imagen en espejo (como selfie)
        frame = cv2.flip(frame, 1)

        # Empieza a medir el procesamiento
        # (solo hace algo en modo TEST)
        metrics.begin_frame()

        # -----------------------------
        # DETECCIÓN
        # -----------------------------

        result = pipeline.process(
            frame,
            measure=metrics.measure
        )

        hand_positions = result.hand_positions

        # -----------------------------
        # TEXTOS DE JUEGO / TEST
        # -----------------------------

        if mode != MODE_TRACKING:

            with metrics.measure("dibujo"):

                put_text(
                    frame,
                    f"Postura: {result.gesture}",
                    (30, 130),
                    (0, 255, 255),
                    0.9
                )

                if result.person_detected:
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
                result.gesture,
                result.person_detected,
                result.candidates
            )

            metrics.draw_overlay(frame)

        # -----------------------------
        # FPS (todos los modos)
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

    pipeline.close()

    # -----------------------------
    # GUARDAR MÉTRICAS Y REPORTE
    # -----------------------------

    # Solo si se usó el modo TEST
    if metrics.frame_count > 0:

        metrics.pause()
        json_path = metrics.save()

        try:
            from evaluacion.generate_report import generate
            generate(json_path)
        except Exception as error:
            print(
                "No se pudo generar el reporte automáticamente: "
                f"{error}"
            )
            print("Puedes generarlo con: python -m evaluacion.generate_report")
