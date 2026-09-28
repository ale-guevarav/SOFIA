"""
REGISTRO DE MÉTRICAS DE DESEMPEÑO - SOFIA

Mide, mientras el sistema está corriendo:

1. FPS promedio
   - FPS real del ciclo completo (cámara + procesamiento + ventana).
   - Capacidad de procesamiento (FPS teóricos si la cámara no limitara).

2. Tiempo de respuesta
   - Latencia de procesamiento por frame (ms), desglosada por etapa:
     pose, manos, gestos y dibujo.
   - Tiempo de reconocimiento por intento (s): desde la señal "YA"
     hasta que el sistema reporta el gesto.

3. Tasa de acierto
   - Mediante "intentos" etiquetados: el evaluador presiona una tecla
     con el gesto esperado y el sistema tiene N segundos para detectarlo.
   - También se calcula precisión, recall, F1 y matriz de confusión.

Controles en la ventana de OpenCV:
    1 = INICIO   2 = RECARGAR   3 = ESCUDO   4 = ATAQUE   5 = FIN
    0 = modo libre (cancela la prueba actual, no registra nada
        y no muestra nada en pantalla)
    x = cancelar intento actual (igual que 0)
    s = guardar JSON en cualquier momento

Mientras una prueba está activa aparece "TESTING: <gesto>"
en rojo parpadeando del lado izquierdo.
"""

import json
import math
import os
import platform
import statistics
import time
from contextlib import contextmanager
from datetime import datetime

import cv2


# -----------------------------
# ETIQUETAS
# -----------------------------

GESTURES = ["INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"]

# Etiqueta para "no debería detectarse nada"
NONE_LABEL = "NINGUNO"

# Valor que usa main.py cuando no hay postura
NO_DETECTION = "---"

ALL_LABELS = GESTURES + [NONE_LABEL]

KEY_TO_GESTURE = {
    ord("1"): "INICIO",
    ord("2"): "RECARGAR",
    ord("3"): "ESCUDO",
    ord("4"): "ATAQUE",
    ord("5"): "FIN",
}

# Teclas que regresan al modo libre
FREE_MODE_KEYS = (ord("0"), ord("x"))

# Posibles resultados de un intento
OUTCOMES = [
    "acierto",         # Se detectó el gesto correcto
    "no_detectado",    # Se acabó el tiempo sin detectar nada
    "confundido",      # Se detectó un gesto distinto al esperado
    "falso_positivo",  # Prueba NINGUNO, pero se detectó algo
]


# =============================================
# FUNCIONES ESTADÍSTICAS
# =============================================

def percentile(values, p):
    """Percentil con interpolación lineal (sin NumPy)."""

    if not values:
        return 0.0

    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)

    return ordered[lower] + (ordered[upper] - ordered[lower]) * (k - lower)


def describe(values, decimals=3):
    """Resumen estadístico de una lista de números."""

    if not values:
        return {
            "n": 0,
            "promedio": 0.0,
            "mediana": 0.0,
            "minimo": 0.0,
            "maximo": 0.0,
            "p95": 0.0,
            "desv_std": 0.0,
        }

    return {
        "n": len(values),
        "promedio": round(statistics.mean(values), decimals),
        "mediana": round(statistics.median(values), decimals),
        "minimo": round(min(values), decimals),
        "maximo": round(max(values), decimals),
        "p95": round(percentile(values, 95), decimals),
        "desv_std": round(statistics.pstdev(values), decimals),
    }


def _pct(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


# =============================================
# REGISTRO DE MÉTRICAS
# =============================================

class PerformanceMetrics:

    def __init__(
        self,
        output_dir="metrics",
        trial_timeout=6.0,
        countdown=2.0,
        result_display_time=1.5,
    ):

        # -----------------------------
        # CONFIGURACIÓN
        # -----------------------------

        self.output_dir = output_dir

        # Segundos que tiene el sistema para
        # detectar el gesto después de "YA"
        self.trial_timeout = trial_timeout

        # Cuenta regresiva antes de empezar
        # a medir (para que la persona se prepare)
        self.countdown = countdown

        # Tiempo que se muestra el resultado
        self.result_display_time = result_display_time

        self.extra_info = {}

        # -----------------------------
        # TIEMPO DE SESIÓN
        # -----------------------------

        self.session_start_dt = datetime.now()
        self.session_start = time.perf_counter()

        # -----------------------------
        # MÉTRICAS POR FRAME
        # -----------------------------

        self.frame_count = 0
        self.person_frames = 0

        # Tiempo entre frames consecutivos (s)
        self.frame_intervals = []

        # Latencia de procesamiento por frame (ms)
        self.processing_times_ms = []

        # Latencia por etapa: {"pose": [ms, ms, ...], ...}
        self.stage_samples = {}

        self._frame_start = None
        self._current_stages = {}
        self._last_frame_end = None

        # -----------------------------
        # LÍNEA DE TIEMPO (1 punto por segundo)
        # -----------------------------

        self.timeline = []
        self._bucket_start = time.perf_counter()
        self._bucket_frames = 0
        self._bucket_processing = []
        self._live_fps = 0.0

        # -----------------------------
        # DETECCIONES
        # -----------------------------

        # Cuántas veces el sistema reportó cada gesto
        self.detection_counts = {g: 0 for g in GESTURES}

        # Detecciones que ocurrieron fuera de un intento
        self.detections_outside_trials = 0

        self._previous_gesture = NO_DETECTION

        # -----------------------------
        # INTENTOS
        # -----------------------------

        self.trials = []

        # idle -> countdown -> active -> result -> idle
        self.state = "idle"

        self.current_expected = None
        self._countdown_until = None
        self._trial_start = None
        self._result_until = 0
        self._last_result = None


    # =============================================
    # INFORMACIÓN EXTRA (cámara, modelo, etc.)
    # =============================================

    def set_info(self, **kwargs):
        self.extra_info.update(kwargs)


    # =============================================
    # MEDICIÓN POR FRAME
    # =============================================

    def begin_frame(self):
        """Llamar justo después de leer el frame de la cámara."""

        self._frame_start = time.perf_counter()
        self._current_stages = {}


    @contextmanager
    def measure(self, stage_name):
        """
        Mide cuánto tarda un bloque de código.

        Uso:
            with metrics.measure("pose"):
                resultado = detector.detect(...)
        """

        start = time.perf_counter()

        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000

            self._current_stages[stage_name] = (
                self._current_stages.get(stage_name, 0.0)
                + elapsed_ms
            )


    def end_frame(self, detected_gesture, person_detected):
        """
        Llamar al final del procesamiento de cada frame
        (antes de cv2.imshow).
        """

        if self._frame_start is None:
            return

        now = time.perf_counter()

        # -----------------------------
        # LATENCIA DE PROCESAMIENTO
        # -----------------------------

        processing_ms = (now - self._frame_start) * 1000
        self.processing_times_ms.append(processing_ms)

        for stage, elapsed_ms in self._current_stages.items():
            self.stage_samples.setdefault(stage, []).append(elapsed_ms)

        # -----------------------------
        # FPS REAL
        # -----------------------------

        if self._last_frame_end is not None:
            self.frame_intervals.append(now - self._last_frame_end)

        self._last_frame_end = now

        self.frame_count += 1

        if person_detected:
            self.person_frames += 1

        # -----------------------------
        # LÍNEA DE TIEMPO
        # -----------------------------

        self._bucket_frames += 1
        self._bucket_processing.append(processing_ms)

        bucket_elapsed = now - self._bucket_start

        if bucket_elapsed >= 1.0:

            self._live_fps = self._bucket_frames / bucket_elapsed

            self.timeline.append({
                "segundo": round(now - self.session_start, 1),
                "fps": round(self._live_fps, 2),
                "latencia_ms": round(
                    statistics.mean(self._bucket_processing), 2
                ),
            })

            self._bucket_start = now
            self._bucket_frames = 0
            self._bucket_processing = []

        # -----------------------------
        # EVENTO DE DETECCIÓN
        # -----------------------------

        # Solo cuenta el momento en que aparece
        # un gesto nuevo (flanco de subida), no
        # cada frame en que sigue visible.
        event = None

        if (
            detected_gesture != NO_DETECTION
            and detected_gesture != self._previous_gesture
        ):
            event = detected_gesture

            if event in self.detection_counts:
                self.detection_counts[event] += 1

        self._previous_gesture = detected_gesture

        self._update_trial(event)


    # =============================================
    # INTENTOS DE EVALUACIÓN
    # =============================================

    def handle_key(self, key):
        """Procesa teclas de evaluación. Regresa True si la usó."""

        if key in KEY_TO_GESTURE and self.state in ("idle", "result"):

            self.current_expected = KEY_TO_GESTURE[key]
            self.state = "countdown"
            self._countdown_until = time.perf_counter() + self.countdown

            print(f"[METRICAS] Prueba de {self.current_expected}: preparate...")
            return True

        # 0 / x: modo libre. Cancela la prueba en curso
        # sin registrar ningún resultado.
        if key in FREE_MODE_KEYS:

            if self.state in ("countdown", "active"):
                print("[METRICAS] Prueba cancelada (modo libre)")

            self.state = "idle"
            self.current_expected = None
            return True

        if key == ord("s"):
            self.save()
            return True

        return False


    def _update_trial(self, event):

        now = time.perf_counter()

        if self.state == "countdown":

            if event is not None:
                self.detections_outside_trials += 1

            if now >= self._countdown_until:
                self.state = "active"
                self._trial_start = now
                print("[METRICAS] YA!")

            return

        if self.state == "active":

            elapsed = now - self._trial_start

            if event is not None:
                self._finish_trial(event, elapsed)

            elif elapsed >= self.trial_timeout:
                self._finish_trial(None, None)

            return

        # idle o result
        if event is not None:
            self.detections_outside_trials += 1

        if self.state == "result" and now >= self._result_until:
            self.state = "idle"


    def _finish_trial(self, detected, response_time):

        expected = self.current_expected

        # -----------------------------
        # CLASIFICAR RESULTADO
        # -----------------------------

        if expected == NONE_LABEL:

            # En la prueba NINGUNO, lo correcto
            # es que NO se detecte nada
            outcome = "acierto" if detected is None else "falso_positivo"

        elif detected == expected:
            outcome = "acierto"

        elif detected is None:
            outcome = "no_detectado"

        else:
            outcome = "confundido"

        trial = {
            "id": len(self.trials) + 1,
            "momento_s": round(time.perf_counter() - self.session_start, 2),
            "esperado": expected,
            "detectado": detected if detected is not None else NONE_LABEL,
            "resultado": outcome,
            "correcto": outcome == "acierto",
            "tiempo_respuesta_s": (
                round(response_time, 3)
                if response_time is not None
                else None
            ),
        }

        self.trials.append(trial)
        self._last_result = trial

        self.state = "result"
        self._result_until = time.perf_counter() + self.result_display_time
        self.current_expected = None

        print(
            f"[METRICAS] Intento {trial['id']}: esperado={trial['esperado']} "
            f"detectado={trial['detectado']} -> {outcome.upper()}"
            + (
                f" ({response_time:.2f}s)"
                if response_time is not None
                else ""
            )
        )


    # =============================================
    # DIBUJAR ESTADO EN PANTALLA
    # =============================================

    def draw_overlay(self, frame):

        now = time.perf_counter()

        # Posición: lado izquierdo, debajo de "Postura"
        position = (30, 180)

        def put(text, color):
            # Contorno negro para que se lea sobre cualquier fondo
            cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (0, 0, 0), 5)
            cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, color, 2)

        # -----------------------------
        # MODO LIBRE: no mostrar nada
        # -----------------------------

        if self.state == "idle":
            return

        # -----------------------------
        # CUENTA REGRESIVA: 3, 2, 1
        # -----------------------------

        if self.state == "countdown":

            remaining = max(1, math.ceil(self._countdown_until - now))
            put(f"TESTING: {self.current_expected}  {remaining}", (0, 200, 255))
            return

        # -----------------------------
        # PRUEBA EN CURSO: TESTING parpadeando
        # -----------------------------

        if self.state == "active":

            # Visible 0.5 s, oculto 0.5 s
            if int(now * 2) % 2 == 0:
                put(f"TESTING: {self.current_expected}  YA!", (0, 0, 255))

            return

        # -----------------------------
        # RESULTADO DEL INTENTO (1.5 s)
        # -----------------------------

        if self.state == "result" and self._last_result:

            result = self._last_result
            ok = result["correcto"]

            # OpenCV no dibuja acentos, por eso
            # los textos van sin tildes
            put(
                f"{'ACIERTO' if ok else 'FALLO'}: {result['detectado']}",
                (0, 255, 0) if ok else (0, 0, 255),
            )


    # =============================================
    # RESUMEN DE MÉTRICAS
    # =============================================

    def build_summary(self):

        duration = time.perf_counter() - self.session_start

        # -----------------------------
        # FPS
        # -----------------------------

        total_interval = sum(self.frame_intervals)

        # FPS promedio = frames / tiempo total.
        # Es más correcto que promediar 1/dt
        # (ese promedio se infla con frames rápidos).
        fps_average = (
            len(self.frame_intervals) / total_interval
            if total_interval > 0
            else 0.0
        )

        instant_fps = [1 / dt for dt in self.frame_intervals if dt > 0]

        processing = describe(self.processing_times_ms)

        processing_capacity = (
            1000 / processing["promedio"]
            if processing["promedio"] > 0
            else 0.0
        )

        # -----------------------------
        # ETAPAS
        # -----------------------------

        stage_means = {
            name: statistics.mean(values)
            for name, values in self.stage_samples.items()
            if values
        }

        stage_total = sum(stage_means.values())

        stages = {}

        for name, values in self.stage_samples.items():
            info = describe(values)
            info["porcentaje"] = (
                round(stage_means[name] / stage_total * 100, 2)
                if stage_total
                else 0.0
            )
            stages[name] = info

        # -----------------------------
        # INTENTOS
        # -----------------------------

        trials = self.trials
        gesture_trials = [t for t in trials if t["esperado"] != NONE_LABEL]
        none_trials = [t for t in trials if t["esperado"] == NONE_LABEL]

        def hits(subset):
            return sum(1 for t in subset if t["correcto"])

        outcome_counts = {o: 0 for o in OUTCOMES}
        for t in trials:
            outcome_counts[t["resultado"]] += 1

        # Matriz de confusión: matriz[esperado][detectado]
        matrix = {
            expected: {predicted: 0 for predicted in ALL_LABELS}
            for expected in ALL_LABELS
        }

        for t in trials:
            matrix[t["esperado"]][t["detectado"]] += 1

        # -----------------------------
        # MÉTRICAS POR GESTO
        # -----------------------------

        per_gesture = {}

        for label in ALL_LABELS:

            subset = [t for t in trials if t["esperado"] == label]

            true_positives = matrix[label][label]
            predicted_total = sum(matrix[e][label] for e in ALL_LABELS)
            actual_total = len(subset)

            precision = (
                true_positives / predicted_total if predicted_total else None
            )
            recall = (
                true_positives / actual_total if actual_total else None
            )

            if precision is not None and recall is not None and (precision + recall) > 0:
                f1 = 2 * precision * recall / (precision + recall)
            elif precision is not None and recall is not None:
                f1 = 0.0
            else:
                f1 = None

            response_times = [
                t["tiempo_respuesta_s"]
                for t in subset
                if t["correcto"] and t["tiempo_respuesta_s"] is not None
            ]

            per_gesture[label] = {
                "intentos": actual_total,
                "aciertos": hits(subset),
                "no_detectado": sum(1 for t in subset if t["resultado"] == "no_detectado"),
                "confundido": sum(1 for t in subset if t["resultado"] == "confundido"),
                "falso_positivo": sum(1 for t in subset if t["resultado"] == "falso_positivo"),
                "tasa_acierto": _pct(hits(subset), actual_total),
                "precision": round(precision * 100, 2) if precision is not None else None,
                "recall": round(recall * 100, 2) if recall is not None else None,
                "f1": round(f1 * 100, 2) if f1 is not None else None,
                "tiempo_respuesta_s": describe(response_times),
            }

        # Tiempo de respuesta global (solo aciertos de gestos reales)
        all_response_times = [
            t["tiempo_respuesta_s"]
            for t in gesture_trials
            if t["correcto"] and t["tiempo_respuesta_s"] is not None
        ]

        response_summary = describe(all_response_times)

        return {
            "resumen": {
                "duracion_s": round(duration, 2),
                "frames_procesados": self.frame_count,
                "porcentaje_frames_con_persona": _pct(self.person_frames, self.frame_count),
                "fps_promedio": round(fps_average, 2),
                "latencia_promedio_ms": processing["promedio"],
                "total_intentos": len(trials),
                "aciertos": hits(trials),
                "tasa_acierto_global": _pct(hits(trials), len(trials)),
                "tasa_reconocimiento_gestos": _pct(hits(gesture_trials), len(gesture_trials)),
                "tasa_rechazo_correcto": _pct(hits(none_trials), len(none_trials)),
                "tiempo_respuesta_promedio_s": (
                    response_summary["promedio"] if response_summary["n"] else None
                ),
            },
            "fps": {
                "promedio_real": round(fps_average, 2),
                "instantaneo": describe(instant_fps, 2),
                "capacidad_procesamiento": round(processing_capacity, 2),
            },
            "latencia_procesamiento_ms": processing,
            "etapas_ms": stages,
            "tiempo_respuesta_s": response_summary,
            "resultados": outcome_counts,
            "por_gesto": per_gesture,
            "matriz_confusion": {
                "etiquetas": ALL_LABELS,
                "valores": matrix,
            },
            "detecciones": {
                "por_gesto": self.detection_counts,
                "fuera_de_prueba": self.detections_outside_trials,
            },
        }


    # =============================================
    # GUARDAR JSON
    # =============================================

    def save(self, filename=None):

        os.makedirs(self.output_dir, exist_ok=True)

        if filename is None:
            filename = f"sesion_{self.session_start_dt:%Y%m%d_%H%M%S}.json"

        path = os.path.join(self.output_dir, filename)

        data = {
            "sesion": {
                "nombre": os.path.splitext(filename)[0],
                "inicio": self.session_start_dt.isoformat(timespec="seconds"),
                "fin": datetime.now().isoformat(timespec="seconds"),
                "configuracion": {
                    "tiempo_limite_intento_s": self.trial_timeout,
                    "cuenta_regresiva_s": self.countdown,
                },
                "sistema": {
                    "so": platform.platform(),
                    "procesador": platform.processor(),
                    "python": platform.python_version(),
                    "opencv": cv2.__version__,
                    **self.extra_info,
                },
            },
            **self.build_summary(),
            "intentos": self.trials,
            "linea_de_tiempo": self.timeline,
        }

        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

        print(f"[METRICAS] Guardado en {path}")

        return path