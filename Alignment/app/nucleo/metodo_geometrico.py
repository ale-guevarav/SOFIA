"""
MÉTODO GEOMÉTRICO (línea base) - SOFIA (diagnóstico de alineación)

Sin entrenamiento. Para cada hexágono, en la foto ENDEREZADA:

    1. Ubicación aproximada: en una ventana alrededor de su posición en
       0,0 se binariza (Otsu) y se busca la plantilla hexagonal (NCC).
    2. Refinamiento: centroide de la mancha clara que contiene ese punto,
       si parece una placa (área y forma razonables); si no, se queda
       el resultado del paso 1.
    3. El desplazamiento (du, dv) respecto a 0,0 da los ángulos.

Cinemática del panel (los dos ejes se cruzan a una distancia L de la placa):

    placa = Rx(theta1) · Ry(theta2) · (0, 0, L)
    =>  dv = L sin(theta2)                (arriba en la imagen)
        du = L cos(theta2) sin(theta1)    (derecha en la imagen)

    theta2 = asin(dv / L)
    theta1 = asin(du / (L cos(theta2)))

Si se da una foto de REFERENCIA (todo en 0,0), primero se mide dónde
quedó cada placa en ella y se usa como cero (corrige pequeños errores
de armado o de medida del módulo real).

Limitación conocida: al inclinarse, la placa también BAJA un poco
(hasta ~1 cm a 27°) y con la perspectiva eso la corre hacia el centro
de la foto. Es despreciable en ángulos chicos, pero agrega error en los
grandes. Los modelos entrenados pueden aprender a compensarlo.
"""

import math

import cv2
import numpy as np

import geometria as g
import preprocesamiento as pp


# Plantilla: hexágono claro (placa) sobre un anillo oscuro (hueco)
ANILLO_M = 0.006
# Cuánto se puede correr la placa: a 30° se mueve L·sin(30°) (~1.9 cm con el
# PROTO); un poco más de margen, pero sin llegar a la placa vecina.
BUSQUEDA_M = g.BRAZO_GDL1 * math.sin(math.radians(g.LIMITE_GRADOS)) + 0.008


def _plantilla():
    ppm = g.PIXELES_POR_METRO
    radio = g.RADIO_HEXAGONO * ppm
    lado = int(math.ceil(2 * (radio + ANILLO_M * ppm))) | 1   # impar
    c = lado / 2 - 0.5

    # Hexágono con un vértice hacia arriba (así se ven en la imagen enderezada)
    vertices = np.array([
        [c + radio * math.cos(math.radians(90 + 60 * k)),
         c - radio * math.sin(math.radians(90 + 60 * k))]
        for k in range(6)
    ], np.float32)

    plantilla = np.zeros((lado, lado), np.float32)
    cv2.fillConvexPoly(plantilla, np.round(vertices * 16).astype(np.int32), 1.0,
                       lineType=cv2.LINE_AA, shift=4)
    return plantilla


PLANTILLA = _plantilla()


def _pico_subpixel(mapa, y, x):
    """Ajuste de parábola alrededor del máximo (en cada eje)."""

    def ajuste(a, b, c):
        denominador = a - 2 * b + c
        return 0.0 if abs(denominador) < 1e-9 else 0.5 * (a - c) / denominador

    dx = ajuste(mapa[y, x - 1], mapa[y, x], mapa[y, x + 1]) if 0 < x < mapa.shape[1] - 1 else 0.0
    dy = ajuste(mapa[y - 1, x], mapa[y, x], mapa[y + 1, x]) if 0 < y < mapa.shape[0] - 1 else 0.0
    return x + dx, y + dy


# Controles para aceptar el centroide de la mancha (paso 2)
AREA_PLACA_PX = 3 * math.sqrt(3) / 2 * (g.RADIO_HEXAGONO * g.PIXELES_POR_METRO) ** 2
AREA_MIN, AREA_MAX = 0.60, 1.15      # fracción del área de la placa en 0,0
SOLIDEZ_MIN = 0.93                   # área / área del casco convexo
SALTO_MAX_PX = 15                    # distancia máxima entre paso 1 y paso 2


def _ventanas(enderezada):
    """Ventana de búsqueda de cada panel y su esquina (x0, y0)."""

    h, w = PLANTILLA.shape
    busqueda = int(round(BUSQUEDA_M * g.PIXELES_POR_METRO))

    for _, fila, columna, _ in g.paneles():
        cx, cy = pp.centro_panel_px(fila, columna)
        x0 = max(int(round(cx - w / 2 - busqueda)), 0)
        y0 = max(int(round(cy - h / 2 - busqueda)), 0)
        yield enderezada[y0:y0 + h + 2 * busqueda, x0:x0 + w + 2 * busqueda], x0, y0


def _ubicar_una(ventana, x0, y0):

    h, w = PLANTILLA.shape

    # Paso 1: plantilla sobre la ventana binarizada
    _, binaria = cv2.threshold(ventana, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mapa = cv2.matchTemplate(binaria.astype(np.float32), PLANTILLA, cv2.TM_CCOEFF_NORMED)
    _, _, _, (mx, my) = cv2.minMaxLoc(mapa)
    px, py = _pico_subpixel(mapa, my, mx)
    bx, by = px + w / 2 - 0.5, py + h / 2 - 0.5

    # Paso 2: centroide de la mancha que contiene ese punto
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    _, etiquetas = cv2.connectedComponents(binaria)
    k = etiquetas[min(max(int(by), 0), etiquetas.shape[0] - 1),
                  min(max(int(bx), 0), etiquetas.shape[1] - 1)]

    if k:
        mancha = (etiquetas == k).astype(np.uint8)
        area = float(mancha.sum())
        contornos, _ = cv2.findContours(mancha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        casco = cv2.convexHull(max(contornos, key=cv2.contourArea))
        solidez = area / max(cv2.contourArea(casco), 1.0)
        m = cv2.moments(mancha, True)
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]

        if (AREA_MIN * AREA_PLACA_PX < area < AREA_MAX * AREA_PLACA_PX
                and solidez > SOLIDEZ_MIN and math.hypot(cx - bx, cy - by) < SALTO_MAX_PX):
            bx, by = cx, cy

    return x0 + bx, y0 + by


def ubicar_placas(enderezada):
    """Centro (x, y) en píxeles de cada una de las 16 placas."""
    return np.array([_ubicar_una(v, x0, y0) for v, x0, y0 in _ventanas(enderezada)])


def desplazamientos(enderezada, centros_cero=None):
    """(du, dv) en metros de cada placa respecto a su posición en 0,0."""

    centros = ubicar_placas(enderezada)

    if centros_cero is None:
        centros_cero = np.array([pp.centro_panel_px(f, c) for _, f, c, _ in g.paneles()])

    du = (centros[:, 0] - centros_cero[:, 0]) / g.PIXELES_POR_METRO
    dv = -(centros[:, 1] - centros_cero[:, 1]) / g.PIXELES_POR_METRO   # filas crecen hacia abajo
    return du, dv


def angulos_desde_desplazamiento(du, dv):
    """Cinemática inversa del panel: (du, dv) -> (theta1, theta2) en grados."""

    theta2 = np.arcsin(np.clip(dv / g.BRAZO_GDL2, -1, 1))
    theta1 = np.arcsin(np.clip(du / (g.BRAZO_GDL1 * np.cos(theta2)), -1, 1))
    return np.degrees(theta1), np.degrees(theta2)


class MetodoGeometrico:
    """
    Uso:
        metodo = MetodoGeometrico(referencia_enderezada)   # o None
        theta1, theta2 = metodo.estimar(enderezada)         # 16 valores cada uno
    """

    def __init__(self, referencia_enderezada=None):
        self.centros_cero = (
            ubicar_placas(referencia_enderezada) if referencia_enderezada is not None else None
        )

    def estimar(self, enderezada):
        du, dv = desplazamientos(enderezada, self.centros_cero)
        return angulos_desde_desplazamiento(du, dv)
