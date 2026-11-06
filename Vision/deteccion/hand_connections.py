# Conexiones de los 21 landmarks de MediaPipe Hand Landmarker

HAND_CONNECTIONS = [
    # Pulgar
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),

    # Índice
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),

    # Medio
    (5, 9),
    (9, 10),
    (10, 11),
    (11, 12),

    # Anular
    (9, 13),
    (13, 14),
    (14, 15),
    (15, 16),

    # Meñique
    (13, 17),
    (17, 18),
    (18, 19),
    (19, 20),

    # Base de la palma
    (0, 17),
]