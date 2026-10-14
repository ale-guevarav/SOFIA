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

Para cada mano detectada devuelve:

    - Coordenadas cartesianas en píxeles      (x, y)
    - Coordenadas normalizadas de -1 a 1      (x_norm, y_norm)
    - Vector desde el origen hasta la mano:
        * componentes (x, y)
        * magnitud |v|
        * ángulo en grados (0° = derecha, sentido antihorario)

En este modo NO se reconocen posturas: solo se usa Hand Landmarker.
"""

import math
from dataclasses import asdict, dataclass

import cv2


# -----------------------------
# CONFIGURACIÓN
# -----------------------------

# Landmarks que forman la palma:
# muñeca + base de los cuatro dedos.
# Su promedio es el "centro de la mano"
# y es más estable que usar un solo punto.
PALM_POINTS = (0, 5, 9, 13, 17)

# MediaPipe decide izquierda/derecha suponiendo
# que la imagen está en espejo (como una selfie).
# main.py NO voltea la imagen, por eso se invierte.
SWAP_HANDEDNESS = True

HAND_LABELS = {
    "Left": "IZQUIERDA",
    "Right": "DERECHA",
}

# Colores BGR por mano
HAND_COLORS = {
    "IZQUIERDA": (255, 200, 0),   # Azul claro
    "DERECHA": (0, 165, 255),     # Naranja
}

DEFAULT_COLOR = (0, 255, 255)

AXIS_COLOR = (220, 220, 220)
GRID_COLOR = (90, 90, 90)


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

    def __init__(self, alpha=0.5):

        # Suavizado EMA de la posición.
        # 1.0 = sin suavizado, más bajo = más estable
        # pero con un poco más de retraso.
        self.alpha = alpha

        # Última posición suavizada de cada mano
        self._previous = {}


    def reset(self):
        self._previous = {}


    # =============================================
    # ETIQUETA DE LA MANO
    # =============================================

    def _get_label(self, result, index):

        if not result.handedness or index >= len(result.handedness):
            return f"MANO {index + 1}"

        name = result.handedness[index][0].category_name

        if SWAP_HANDEDNESS:
            name = "Right" if name == "Left" else "Left"

        return HAND_LABELS.get(name, name.upper())


    # =============================================
    # CALCULAR POSICIONES
    # =============================================

    def update(self, hand_result, frame_shape):
        """
        Recibe el resultado de Hand Landmarker y regresa
        una lista de HandPosition (una por mano),
        ordenada de izquierda a derecha en la pantalla.
        """

        height, width = frame_shape[:2]

        # Origen del plano = centro de la imagen
        center_x = width / 2
        center_y = height / 2

        positions = []

        if not hand_result.hand_landmarks:
            self.reset()
            return positions

        seen = set()

        for index, hand_landmarks in enumerate(hand_result.hand_landmarks):

            label = self._get_label(hand_result, index)

            # Si MediaPipe etiqueta las dos manos igual,
            # se separan para no mezclar el suavizado
            key = label if label not in seen else f"{label}_{index}"
            seen.add(key)

            # -----------------------------
            # CENTRO DE LA PALMA (píxeles)
            # -----------------------------

            pixel_x = (
                sum(hand_landmarks[i].x for i in PALM_POINTS)
                / len(PALM_POINTS)
            ) * width

            pixel_y = (
                sum(hand_landmarks[i].y for i in PALM_POINTS)
                / len(PALM_POINTS)
            ) * height

            # -----------------------------
            # SUAVIZADO EMA
            # -----------------------------

            previous = self._previous.get(key)

            if previous is not None:
                pixel_x = self.alpha * pixel_x + (1 - self.alpha) * previous[0]
                pixel_y = self.alpha * pixel_y + (1 - self.alpha) * previous[1]

            self._previous[key] = (pixel_x, pixel_y)

            # -----------------------------
            # PLANO CARTESIANO
            # -----------------------------

            # En la imagen +y va hacia abajo;
            # en el plano cartesiano +y va hacia arriba
            x = pixel_x - center_x
            y = center_y - pixel_y

            x_norm = x / center_x
            y_norm = y / center_y

            # -----------------------------
            # VECTOR
            # -----------------------------

            magnitude = math.hypot(x, y)
            magnitude_norm = math.hypot(x_norm, y_norm)

            # atan2 da el ángulo respecto al eje +x;
            # % 360 lo deja entre 0 y 360
            angle = math.degrees(math.atan2(y, x)) % 360

            positions.append(HandPosition(
                label=label,
                pixel_x=int(pixel_x),
                pixel_y=int(pixel_y),
                x=round(x, 1),
                y=round(y, 1),
                x_norm=round(x_norm, 3),
                y_norm=round(y_norm, 3),
                magnitude=round(magnitude, 1),
                magnitude_norm=round(magnitude_norm, 3),
                angle=round(angle, 1),
            ))

        # Olvidar manos que ya no están
        self._previous = {
            k: v for k, v in self._previous.items() if k in seen
        }

        positions.sort(key=lambda p: p.x)

        return positions


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

    def draw_positions(self, frame, positions):

        height, width = frame.shape[:2]
        origin = (width // 2, height // 2)

        # -----------------------------
        # VECTORES
        # -----------------------------

        for position in positions:

            color = HAND_COLORS.get(position.label, DEFAULT_COLOR)
            point = (position.pixel_x, position.pixel_y)

            cv2.arrowedLine(frame, origin, point, color, 3, tipLength=0.05)
            cv2.circle(frame, point, 8, color, -1)
            cv2.circle(frame, point, 8, (0, 0, 0), 2)

            _put_text(
                frame,
                f"({position.x:+.0f}, {position.y:+.0f})",
                (point[0] + 12, point[1] - 12),
                color,
                0.6,
            )

        # -----------------------------
        # PANEL DE INFORMACIÓN
        # -----------------------------

        if positions:
            lines = []
            for position in positions:
                color = HAND_COLORS.get(position.label, DEFAULT_COLOR)
                lines += [
                    (f"MANO {position.label}", color),
                    (f"  Coord:  x={position.x:+.0f}  y={position.y:+.0f} px", (255, 255, 255)),
                    (f"  Norm:   x={position.x_norm:+.2f}  y={position.y_norm:+.2f}", (255, 255, 255)),
                    (f"  Vector: |v|={position.magnitude:.0f} px  ang={position.angle:.1f} deg", (255, 255, 255)),
                ]
        else:
            lines = [("Sin mano detectada", (0, 0, 255))]

        line_height = 24
        panel_height = line_height * len(lines) + 16
        panel_width = 430

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
                scale, (0, 0, 0), 4)
    cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, 1 if scale < 0.6 else 2)