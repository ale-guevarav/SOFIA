# Conexiones entre los landmarks de MediaPipe Pose

POSE_CONNECTIONS = [
    # Cara
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 7),
    (0, 4),
    (4, 5),
    (5, 6),
    (6, 8),
    (9, 10),

    # Hombros y torso
    (11, 12),
    (11, 23),
    (12, 24),
    (23, 24),

    # Brazo izquierdo
    (11, 13),
    (13, 15),

    # Mano izquierda
    (15, 17),
    (15, 19),
    (15, 21),
    (17, 19),

    # Brazo derecho
    (12, 14),
    (14, 16),

    # Mano derecha
    (16, 18),
    (16, 20),
    (16, 22),
    (18, 20),

    # Pierna izquierda
    (23, 25),
    (25, 27),

    # Pie izquierdo
    (27, 29),
    (29, 31),
    (27, 31),

    # Pierna derecha
    (24, 26),
    (26, 28),

    # Pie derecho
    (28, 30),
    (30, 32),
    (28, 32),
]