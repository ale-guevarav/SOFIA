"""
GEOMETRÍA DEL MÓDULO Y DEL MARCO - SOFIA (diagnóstico de alineación)

Fuente ÚNICA de las medidas. La usan:
    - build/herramientas/crear_mundo_dataset.py  (arma los mundos de Webots)
    - build/herramientas/generar_marcadores.py   (texturas e impresión de ArUco)
    - el preprocesamiento (enderezar la foto y recortar los hexágonos)

Cuando llegue el módulo real, se cambian aquí las medidas y se
vuelven a generar el mundo y el dataset.

SISTEMAS DE COORDENADAS
-----------------------
Mundo de Webots (ENU, metros):  x, y en el piso, z hacia arriba.

Imagen ENDEREZADA (vista desde arriba, como la cámara cenital):
    u = derecha  = -Y del mundo
    v = arriba   = +X del mundo
Con el centro del arreglo en (u, v) = (0, 0).

Ángulos de cada panel (los que estima el modelo):
    theta1 = joint_1 (eje X del mundo): positivo inclina la placa hacia -Y,
             es decir, hacia la DERECHA de la imagen.
    theta2 = joint_3 (eje Y del mundo): positivo inclina hacia +X,
             es decir, hacia ARRIBA de la imagen.
"""

import math


# =============================================
# ARREGLO DE 4 x 4 HEXÁGONOS (PROTO sofia en Webots)
# =============================================

FILAS = 4
COLUMNAS = 4

# Posición (x, y) del centro de cada panel en el mundo.
# Filas pares e impares están desfasadas (arreglo tipo panal).
# Separación mínima sin choques con las placas a ±30° (igual que sofia.wbt):
# 140 mm en la fila y 116 mm entre filas.
FILAS_X = [-0.174, -0.058, 0.058, 0.174]
COLUMNAS_Y_PAR = [-0.210, -0.070, 0.070, 0.210]
COLUMNAS_Y_IMPAR = [-0.140, 0.000, 0.140, 0.280]

# Centro del arreglo (promedio de los 16 paneles)
CENTRO_X = 0.0
CENTRO_Y = 0.035

# Placa hexagonal
RADIO_HEXAGONO = 0.060         # m, centro a vértice (120 mm de punta a punta)

# Altura de la cara superior de las placas con el panel en 0,0 (m)
# ejes a 0.022 sobre el piso + 0.037 de los ejes a la cara de la placa
ALTURA_PLACAS = 0.059

# Distancia de los ejes a la placa (para el método geométrico).
# En el PROTO los dos ejes se cruzan en el mismo punto (z = 0.022).
BRAZO_GDL1 = 0.037             # eje joint_1 -> cara de la placa
BRAZO_GDL2 = 0.037             # eje joint_3 -> cara de la placa

# Tope mecánico (±30°) y tope seguro de los controladores
LIMITE_GRADOS = 30.0
LIMITE_SEGURO_GRADOS = 27.5


def panel_xy(fila, columna):
    """Centro (x, y) del panel en el mundo."""
    columnas_y = COLUMNAS_Y_IMPAR if fila % 2 else COLUMNAS_Y_PAR
    return FILAS_X[fila], columnas_y[columna]


def mundo_a_imagen(x, y):
    """(x, y) del mundo -> (u, v) de la imagen enderezada, en metros."""
    return -(y - CENTRO_Y), x - CENTRO_X


def paneles():
    """Lista de (indice, fila, columna, nombre) de los 16 paneles."""
    return [
        (fila * COLUMNAS + columna, fila, columna, f"Panel_{fila}_{columna}")
        for fila in range(FILAS)
        for columna in range(COLUMNAS)
    ]


# =============================================
# MARCO CON MARCADORES ARUCO
# =============================================

# Diccionario de OpenCV (cv2.aruco)
ARUCO_DICCIONARIO = "DICT_4X4_50"

# Lado del marcador negro (m) y del cuadro blanco que lo rodea
LADO_MARCADOR = 0.060
LADO_CUADRO_BLANCO = 0.080

# Los centros de los 4 marcadores forman un cuadrado de este lado,
# centrado en el arreglo (m). Es el más chico en el que ningún cuadro
# blanco toca el área que barren las placas a ±30° (70.5 mm desde su
# centro), con ~15 mm de margen: 0.597 m, redondeado a 0.60 m.
LADO_MARCO = 0.600

# Marcador -> esquina, en la imagen enderezada (u, v):
#   0 arriba-izquierda, 1 arriba-derecha, 2 abajo-derecha, 3 abajo-izquierda
ESQUINAS_UV = {
    0: (-LADO_MARCO / 2, +LADO_MARCO / 2),
    1: (+LADO_MARCO / 2, +LADO_MARCO / 2),
    2: (+LADO_MARCO / 2, -LADO_MARCO / 2),
    3: (-LADO_MARCO / 2, -LADO_MARCO / 2),
}


def imagen_a_mundo(u, v):
    """(u, v) de la imagen enderezada -> (x, y) del mundo."""
    return v + CENTRO_X, -u + CENTRO_Y


def esquinas_mundo():
    """Centro (x, y) de cada marcador en el mundo."""
    return {id_: imagen_a_mundo(u, v) for id_, (u, v) in ESQUINAS_UV.items()}


# =============================================
# IMAGEN ENDEREZADA Y RECORTES
# =============================================

# Resolución de la imagen enderezada
PIXELES_POR_METRO = 1000        # 1 px = 1 mm (similar a la cámara)
MARGEN_M = 0.06                 # margen alrededor del marco (los recortes de las
                                # placas de las orillas llegan a 0.345 m del centro)

LADO_ENDEREZADA_PX = int(round((LADO_MARCO + 2 * MARGEN_M) * PIXELES_POR_METRO))

# Recorte de cada hexágono: un poco más grande que la placa para que
# quepa aunque esté inclinada 30° (se corre ~4 cm)
LADO_RECORTE_M = 2 * RADIO_HEXAGONO + 0.08
LADO_RECORTE_PX = 128           # tamaño final que recibe el modelo


def uv_a_pixel(u, v):
    """(u, v) en metros -> (columna, fila) en la imagen enderezada."""
    mitad = LADO_ENDEREZADA_PX / 2
    return mitad + u * PIXELES_POR_METRO, mitad - v * PIXELES_POR_METRO


# =============================================
# ESTADOS DE ALINEACIÓN
# =============================================

UMBRAL_OK_GRADOS = 2.0          # |theta| < 2°   -> OK
UMBRAL_MAL_GRADOS = 5.0         # 2° a 5°        -> revisar ; > 5° -> desalineado


def desalineacion(theta1_grados, theta2_grados):
    """Magnitud (°), porcentaje del tope y estado de un hexágono."""

    magnitud = math.hypot(theta1_grados, theta2_grados)
        # Porcentaje del recorrido del eje más desviado (0-100 %)
    porcentaje = max(abs(theta1_grados), abs(theta2_grados)) / LIMITE_GRADOS * 100

    if magnitud < UMBRAL_OK_GRADOS:
        estado = "OK"
    elif magnitud <= UMBRAL_MAL_GRADOS:
        estado = "REVISAR"
    else:
        estado = "DESALINEADO"

    return magnitud, porcentaje, estado
