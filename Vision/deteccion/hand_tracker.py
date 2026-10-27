"""
MODO TRACKING - SOFIA

Sigue la posición de la mano y la expresa en un plano cartesiano
con el origen (0, 0) en el CENTRO de la imagen:

            +y
             |
             |
    -x ------+------ +x
             |
             |
            -y

Solo sigue la mano de TRACKING_HAND (la derecha); la otra se ignora.

Para la mano seguida devuelve:

    - Coordenadas cartesianas en píxeles      (x, y)
    - Coordenadas normalizadas de -1 a 1      (x_norm, y_norm)
    - Vector desde el origen hasta la mano:
        * componentes (x, y)
        * magnitud |v|
        * ángulo en grados (0° = derecha, sentido antihorario)

En este modo NO se reconocen posturas.

CONSISTENCIA (cuando la palma no mira a la cámara)
--------------------------------------------------
Hand Landmarker pierde la mano cuando la palma se inclina mucho.
Para no perder el seguimiento se usan tres niveles, en orden:

    1. "mano"    -> Hand Landmarker (lo más preciso).
    2. "pose"    -> Si la mano se perdió, se usa la muñeca/mano
                    que da Pose Landmarker, que sigue el brazo
                    completo y no depende de ver la palma.
                    Solo continúa manos que ya se venían siguiendo.
    3. "memoria" -> Si tampoco hay pose, se mantiene la última
                    posición durante un instante (hold_time)
                    para tapar parpadeos de uno o dos frames.
"""

import math
import time
from dataclasses import asdict, dataclass
from types import SimpleNamespace

import cv2


# -----------------------------
# CONFIGURACIÓN
# -----------------------------

# Landmarks de Hand Landmarker que forman la palma:
# muñeca + base de los cuatro dedos.
# Su promedio es el "centro de la mano".
PALM_POINTS = (0, 5, 9, 13, 17)

# Landmarks de Pose Landmarker de cada mano:
# muñeca, meñique e índice.
POSE_HAND_POINTS = {
    "IZQUIERDA": (15, 17, 19),
    "DERECHA": (16, 18, 20),
}

# MediaPipe Hands decide izquierda/derecha suponiendo
# que la imagen está en espejo (como una selfie).
# main.py y la GUI ya voltean la imagen (cv2.flip),
# así que no hace falta invertir.
SWAP_HANDEDNESS = False

# Mano que se sigue en modo TRACKING: "DERECHA", "IZQUIERDA"
# o None para seguir las dos. La otra mano se ignora aunque se vea
# (se siguen detectando 2 manos para que la otra no le gane el lugar).
TRACKING_HAND = "DERECHA"

HAND_LABELS = {
    "Left": "IZQUIERDA",
    "Right": "DERECHA",
}

OTHER_HAND = {
    "IZQUIERDA": "DERECHA",
    "DERECHA": "IZQUIERDA",
}

# Colores BGR por mano
HAND_COLORS = {
    "IZQUIERDA": (255, 200, 0),   # Azul claro
    "DERECHA": (0, 165, 255),     # Naranja
}

DEFAULT_COLOR = (0, 255, 255)

AXIS_COLOR = (220, 220, 220)
GRID_COLOR = (90, 90, 90)

SOURCE_LABELS = {
    "mano": "",
    "pose": " (por pose)",
    "memoria": " (estimada)",
}


# =============================================
# DATOS DE UNA MANO
# =============================================

@dataclass
class HandPosition:

    # "IZQUIERDA" / "DERECHA"
    label: str

    # Posición en la imagen (origen arriba-izquierda)
    pixel_x: int
    pixel_y: int

    # Coordenadas cartesianas en píxeles
    # (origen en el centro, +y hacia arriba)
    x: float
    y: float

    # Coordenadas normalizadas:
    # -1 = borde izquierdo/inferior
    # +1 = borde derecho/superior
    x_norm: float
    y_norm: float

    # Magnitud del vector
    magnitude: float
    magnitude_norm: float

    # Ángulo del vector en grados (0 - 360)
    angle: float

    # De dónde salió la posición: "mano", "pose" o "memoria"
    source: str = "mano"


    @property
    def vector(self):
        """Vector desde el origen (0, 0) hasta la mano."""
        return (self.x, self.y)


    @property
    def vector_norm(self):
        """Vector normalizado (-1 a 1 en cada eje)."""
        return (self.x_norm, self.y_norm)


    def as_dict(self):
        return asdict(self)


# =============================================
# TRACKER
# =============================================

class HandTracker:

    def __init__(
        self,
        alpha=0.5,
        hold_time=0.35,
        fallback_window=1.0,
        pose_min_visibility=0.5,
        only_hand=TRACKING_HAND,
    ):

        # Solo esta mano ("DERECHA" / "IZQUIERDA"); None = las dos
        self.only_hand = only_hand

        # Índices (en el resultado de Hand Landmarker) de las manos
        # que se siguieron en el último update(), para dibujar solo esas
        self._tracked_indices = []

        # Suavizado EMA de la posición.
        # 1.0 = sin suavizado, más bajo = más estable
        # pero con un poco más de retraso.
        self.alpha = alpha

        # Segundos que se conserva la última posición
        # cuando no hay ni mano ni pose
        self.hold_time = hold_time

        # Segundos durante los que una mano perdida
        # se puede seguir con Pose
        self.fallback_window = fallback_window

        # Visibilidad mínima de la muñeca en Pose
        self.pose_min_visibility = pose_min_visibility

        # Última posición suavizada (px) de cada mano
        self._previous = {}

        # Último momento en que se vio cada mano
        # (por Hand Landmarker o por Pose)
        self._last_seen = {}


    def reset(self):
        self._previous = {}
        self._last_seen = {}


    # =============================================
    # ¿HACE FALTA CORRER POSE?
    # =============================================

    def needs_pose_fallback(self, hand_result, now=None):
        """
        True si se perdió alguna mano que se venía siguiendo.
        Así Pose solo se ejecuta cuando hace falta
        y no se pierden FPS el resto del tiempo.
        """

        now = time.monotonic() if now is None else now

        recent = self._recent_labels(now)
        detected = sum(
            1 for index in range(len(hand_result.hand_landmarks or []))
            if self._wanted(self._get_label(hand_result, index))
        )

        return detected < len(recent)


    def _wanted(self, label):
        return self.only_hand is None or label == self.only_hand


    def _recent_labels(self, now):
        return {
            label for label, seen in self._last_seen.items()
            if now - seen <= self.fallback_window
        }


    # =============================================
    # ETIQUETA DE LA MANO
    # =============================================

    def _get_label(self, result, index):

        if not result.handedness or index >= len(result.handedness):
            return None

        name = result.handedness[index][0].category_name

        if SWAP_HANDEDNESS:
            name = "Right" if name == "Left" else "Left"

        return HAND_LABELS.get(name)


    def only_tracked(self, hand_result):
        """
        El resultado de Hand Landmarker solo con las manos que se siguieron
        en el último update() (para no dibujar la otra mano).
        """
        landmarks = hand_result.hand_landmarks or []
        handedness = hand_result.handedness or []
        return SimpleNamespace(
            hand_landmarks=[landmarks[i] for i in self._tracked_indices if i < len(landmarks)],
            handedness=[handedness[i] for i in self._tracked_indices if i < len(handedness)],
        )


    # =============================================
    # CALCULAR POSICIONES
    # =============================================

    def update(self, hand_result, frame_shape, pose_result=None, now=None):
        """
        Recibe el resultado de Hand Landmarker (y opcionalmente
        el de Pose Landmarker) y regresa una lista de
        HandPosition, ordenada de izquierda a derecha.
        """

        now = time.monotonic() if now is None else now

        height, width = frame_shape[:2]

        # label -> (pixel_x, pixel_y, source)
        raw = {}
        self._tracked_indices = []

        # -----------------------------
        # 1. HAND LANDMARKER
        # -----------------------------

        for index, hand_landmarks in enumerate(hand_result.hand_landmarks or []):

            label = self._get_label(hand_result, index)

            # Si no hay etiqueta o se repite,
            # se asigna la mano que falta
            if label is None or label in raw:
                label = next(
                    (l for l in ("IZQUIERDA", "DERECHA") if l not in raw),
                    None,
                )
                if label is None:
                    continue

            # La otra mano no se sigue
            if not self._wanted(label):
                continue

            self._tracked_indices.append(index)

            pixel_x = sum(hand_landmarks[i].x for i in PALM_POINTS) / len(PALM_POINTS) * width
            pixel_y = sum(hand_landmarks[i].y for i in PALM_POINTS) / len(PALM_POINTS) * height

            raw[label] = (pixel_x, pixel_y, "mano")

        # -----------------------------
        # 2. RESPALDO CON POSE
        # -----------------------------

        recent = self._recent_labels(now)

        if pose_result is not None and pose_result.pose_landmarks:

            pose_landmarks = pose_result.pose_landmarks[0]

            for label in recent - raw.keys():

                points = [pose_landmarks[i] for i in POSE_HAND_POINTS[label]]
                wrist = points[0]

                if getattr(wrist, "visibility", 1.0) < self.pose_min_visibility:
                    continue

                pixel_x = sum(p.x for p in points) / len(points) * width
                pixel_y = sum(p.y for p in points) / len(points) * height

                raw[label] = (pixel_x, pixel_y, "pose")

        # Las manos vistas (por mano o por pose)
        # renuevan su tiempo
        for label in raw:
            self._last_seen[label] = now

        # -----------------------------
        # 3. MEMORIA CORTA
        # -----------------------------

        for label in list(self._previous.keys()):

            if label in raw:
                continue

            seen = self._last_seen.get(label)

            if seen is not None and now - seen <= self.hold_time:
                pixel_x, pixel_y = self._previous[label]
                raw[label] = (pixel_x, pixel_y, "memoria")

        # -----------------------------
        # SUAVIZADO + PLANO CARTESIANO
        # -----------------------------

        positions = []

        for label, (pixel_x, pixel_y, source) in raw.items():

            previous = self._previous.get(label)

            if previous is not None and source != "memoria":
                pixel_x = self.alpha * pixel_x + (1 - self.alpha) * previous[0]
                pixel_y = self.alpha * pixel_y + (1 - self.alpha) * previous[1]

            self._previous[label] = (pixel_x, pixel_y)

            positions.append(
                self._build_position(label, pixel_x, pixel_y, source, width, height)
            )

        # Olvidar manos que ya no están
        self._previous = {
            label: value for label, value in self._previous.items()
            if label in raw
        }

        self._last_seen = {
            label: seen for label, seen in self._last_seen.items()
            if now - seen <= self.fallback_window
        }

        positions.sort(key=lambda p: p.x)

        return positions


    def _build_position(self, label, pixel_x, pixel_y, source, width, height):

        # Origen del plano = centro de la imagen
        center_x = width / 2
        center_y = height / 2

        # En la imagen +y va hacia abajo;
        # en el plano cartesiano +y va hacia arriba
        x = pixel_x - center_x
        y = center_y - pixel_y

        x_norm = x / center_x
        y_norm = y / center_y

        # atan2 da el ángulo respecto al eje +x;
        # % 360 lo deja entre 0 y 360
        angle = math.degrees(math.atan2(y, x)) % 360

        return HandPosition(
            label=label,
            pixel_x=int(pixel_x),
            pixel_y=int(pixel_y),
            x=round(x, 1),
            y=round(y, 1),
            x_norm=round(x_norm, 3),
            y_norm=round(y_norm, 3),
            magnitude=round(math.hypot(x, y), 1),
            magnitude_norm=round(math.hypot(x_norm, y_norm), 3),
            angle=round(angle, 1),
            source=source,
        )


    # =============================================
    # DIBUJAR PLANO CARTESIANO
    # =============================================

    def draw_plane(self, frame, grid_step=100):

        height, width = frame.shape[:2]
        center_x = width // 2
        center_y = height // 2

        # Cuadrícula tenue cada grid_step píxeles
        for offset in range(grid_step, max(width, height), grid_step):

            for x in (center_x - offset, center_x + offset):
                if 0 <= x < width:
                    cv2.line(frame, (x, 0), (x, height), GRID_COLOR, 1)

            for y in (center_y - offset, center_y + offset):
                if 0 <= y < height:
                    cv2.line(frame, (0, y), (width, y), GRID_COLOR, 1)

        # Ejes
        cv2.line(frame, (0, center_y), (width, center_y), AXIS_COLOR, 2)
        cv2.line(frame, (center_x, 0), (center_x, height), AXIS_COLOR, 2)

        # Etiquetas de los ejes
        _put_text(frame, "+x", (width - 40, center_y - 10), AXIS_COLOR, 0.6)
        _put_text(frame, "+y", (center_x + 10, 25), AXIS_COLOR, 0.6)
        _put_text(frame, "(0,0)", (center_x + 8, center_y + 22), AXIS_COLOR, 0.5)

        # Origen
        cv2.circle(frame, (center_x, center_y), 5, AXIS_COLOR, -1)


    # =============================================
    # DIBUJAR VECTORES E INFORMACIÓN
    # =============================================

    def draw_positions(self, frame, positions, panel=True):

        height, width = frame.shape[:2]
        origin = (width // 2, height // 2)

        # -----------------------------
        # VECTORES
        # -----------------------------

        for position in positions:

            color = HAND_COLORS.get(position.label, DEFAULT_COLOR)
            point = (position.pixel_x, position.pixel_y)

            # Las posiciones estimadas se dibujan más delgadas
            estimated = position.source == "memoria"
            thickness = 1 if estimated else 3

            cv2.arrowedLine(frame, origin, point, color, thickness, tipLength=0.05)

            if estimated:
                cv2.circle(frame, point, 8, color, 2)
            else:
                cv2.circle(frame, point, 8, color, -1)
                cv2.circle(frame, point, 8, (0, 0, 0), 2)

            _put_text(
                frame,
                f"({position.x:+.0f}, {position.y:+.0f})",
                (point[0] + 12, point[1] - 12),
                color,
                0.6,
            )

        if not panel:
            return

        # -----------------------------
        # PANEL DE INFORMACIÓN
        # -----------------------------

        if positions:
            lines = []
            for position in positions:
                color = HAND_COLORS.get(position.label, DEFAULT_COLOR)
                lines += [
                    (f"MANO {position.label}{SOURCE_LABELS.get(position.source, '')}", color),
                    (f"  Coord:  x={position.x:+.0f}  y={position.y:+.0f} px", (255, 255, 255)),
                    (f"  Norm:   x={position.x_norm:+.2f}  y={position.y_norm:+.2f}", (255, 255, 255)),
                    (f"  Vector: |v|={position.magnitude:.0f} px  ang={position.angle:.1f} deg", (255, 255, 255)),
                ]
        else:
            lines = [("Sin mano detectada", (0, 0, 255))]

        line_height = 24
        panel_height = line_height * len(lines) + 16
        panel_width = 460

        top = height - panel_height - 10
        left = 10

        # Fondo semitransparente
        overlay = frame.copy()
        cv2.rectangle(
            overlay,
            (left, top),
            (left + panel_width, top + panel_height),
            (0, 0, 0),
            -1,
        )
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        y = top + 26
        for text, color in lines:
            _put_text(frame, text, (left + 10, y), color, 0.55)
            y += line_height


# =============================================
# UTILIDADES
# =============================================

def _put_text(frame, text, position, color, scale):
    # Contorno negro para que se lea sobre cualquier fondo
    cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, 1 if scale < 0.6 else 2, cv2.LINE_AA)
