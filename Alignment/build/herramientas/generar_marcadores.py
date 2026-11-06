"""
MARCADORES ARUCO DEL MARCO - SOFIA

Genera:
    1. Las texturas para Webots (Webots/Sofia/worlds/textures/aruco_N.png).
    2. Una hoja para IMPRIMIR los 4 marcadores a tamaño real
       (Alignment/results/marcadores_imprimir.png, a 300 dpi), para el marco
       del módulo físico.

Uso (desde la carpeta SOFIA):
    python Alignment/build/herramientas/generar_marcadores.py

Al imprimir: escala 100 % (sin "ajustar a la página") y medir que el
cuadro negro mida exactamente LADO_MARCADOR (geometria.py).
"""

import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(AQUI)), "app", "nucleo"))

import geometria as g  # noqa: E402
import rutas  # noqa: E402


TEXTURAS = os.path.join(rutas.RAIZ, "Webots", "Sofia", "worlds", "textures")
TEXTURA_PX = 400            # resolución de cada textura en Webots
DPI = 300


def diccionario():
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, g.ARUCO_DICCIONARIO))


def marcador_con_borde(id_, lado_px):
    """Marcador negro dentro de su cuadro blanco (zona de silencio)."""

    lado_marcador = int(round(lado_px * g.LADO_MARCADOR / g.LADO_CUADRO_BLANCO))
    marcador = cv2.aruco.generateImageMarker(diccionario(), id_, lado_marcador)

    imagen = np.full((lado_px, lado_px), 255, np.uint8)
    inicio = (lado_px - lado_marcador) // 2
    imagen[inicio:inicio + lado_marcador, inicio:inicio + lado_marcador] = marcador
    return imagen


def generar_texturas():
    os.makedirs(TEXTURAS, exist_ok=True)

    for id_ in g.ESQUINAS_UV:
        ruta = os.path.join(TEXTURAS, f"aruco_{id_}.png")
        cv2.imwrite(ruta, marcador_con_borde(id_, TEXTURA_PX))
        print(f"Textura: {ruta}")


def generar_hoja_impresion():
    """4 marcadores a tamaño real con su número, en una hoja carta."""

    px_por_m = DPI / 0.0254
    lado = int(round(g.LADO_CUADRO_BLANCO * px_por_m))

    ancho, alto = int(8.5 * DPI), int(11 * DPI)
    hoja = np.full((alto, ancho), 255, np.uint8)

    posiciones = [(0.25, 0.22), (0.75, 0.22), (0.75, 0.62), (0.25, 0.62)]
    nombres = {0: "arriba-izquierda", 1: "arriba-derecha",
               2: "abajo-derecha", 3: "abajo-izquierda"}

    for id_, (fx, fy) in zip(g.ESQUINAS_UV, posiciones):
        x = int(fx * ancho - lado / 2)
        y = int(fy * alto - lado / 2)
        hoja[y:y + lado, x:x + lado] = marcador_con_borde(id_, lado)
        cv2.rectangle(hoja, (x, y), (x + lado, y + lado), 180, 2)   # línea de corte
        cv2.putText(hoja, f"ID {id_}: {nombres[id_]}", (x, y + lado + 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 4)

    texto = (f"Cuadro negro = {g.LADO_MARCADOR * 1000:.0f} mm. Imprimir al 100 %. "
             f"Centros en un cuadrado de {g.LADO_MARCO * 1000:.0f} mm, a la altura de las placas.")
    cv2.putText(hoja, texto, (150, alto - 200), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 3)

    ruta = os.path.join(rutas.RESULTS, "marcadores_imprimir.png")
    cv2.imwrite(ruta, hoja)
    print(f"Hoja para imprimir: {ruta}")


if __name__ == "__main__":
    generar_texturas()
    generar_hoja_impresion()
