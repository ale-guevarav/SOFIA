import math


# -----------------------------
# DISTANCIA ENTRE DOS PUNTOS
# -----------------------------

def distance(point_a, point_b):
    """
    Calcula la distancia euclidiana entre dos landmarks.
    """

    dx = point_a.x - point_b.x
    dy = point_a.y - point_b.y

    return math.sqrt(dx ** 2 + dy ** 2)


# -----------------------------
# ÁNGULO ENTRE TRES PUNTOS
# -----------------------------

def angle(point_a, point_b, point_c):
    """
    Calcula el ángulo ABC en grados.
    El punto B representa el vértice del ángulo.
    """

    vector_ba = (
        point_a.x - point_b.x,
        point_a.y - point_b.y
    )

    vector_bc = (
        point_c.x - point_b.x,
        point_c.y - point_b.y
    )

    dot_product = (
        vector_ba[0] * vector_bc[0]
        + vector_ba[1] * vector_bc[1]
    )

    magnitude_ba = math.sqrt(
        vector_ba[0] ** 2
        + vector_ba[1] ** 2
    )

    magnitude_bc = math.sqrt(
        vector_bc[0] ** 2
        + vector_bc[1] ** 2
    )

    if magnitude_ba == 0 or magnitude_bc == 0:
        return 0

    cosine_angle = dot_product / (
        magnitude_ba * magnitude_bc
    )

    # Evitar errores numéricos como 1.0000001
    cosine_angle = max(-1.0, min(1.0, cosine_angle))

    return math.degrees(
        math.acos(cosine_angle)
    )


# -----------------------------
# DISTANCIA NORMALIZADA
# -----------------------------

def normalized_distance(point_a, point_b, reference_a, reference_b):
    """
    Calcula la distancia entre dos landmarks y la normaliza
    utilizando otra distancia corporal como referencia.
    """

    target_distance = distance(
        point_a,
        point_b
    )

    reference_distance = distance(
        reference_a,
        reference_b
    )

    if reference_distance == 0:
        return 0

    return target_distance / reference_distance