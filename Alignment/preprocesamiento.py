"""
PREPROCESAMIENTO - SOFIA (diagnóstico de alineación)

De una foto del módulo (de Webots o de la cámara real) obtiene:

    1. Los 4 marcadores ArUco del marco (su centro en la foto).
    2. La foto ENDEREZADA: vista desde arriba, siempre del mismo tamaño
       y con cada hexágono en el mismo lugar (homografía con los 4 centros).
    3. Los 16 RECORTES, uno por hexágono, que recibe el modelo.

    foto ──► marcadores ──► homografía ──► enderezada ──► 16 recortes

Como el marco está a la altura de las placas, la homografía es exacta
en ese plano: no importa dónde esté la cámara ni qué tan inclinada.

Uso como módulo:
    from preprocesamiento import procesar
    resultado = procesar(imagen_bgr)
    resultado.recortes[indice]     # 128 x 128, escala de grises

Todas las medidas salen de geometria.py.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

import geometria as g


# =============================================
# MARCADORES
# =============================================

_detector = None


def detector():
    """Detector de ArUco (se crea una sola vez)."""

    global _detector

    if _detector is None:
        diccionario = cv2.aruco.getPredefinedDictionary(
            getattr(cv2.aruco, g.ARUCO_DICCIONARIO)
        )
        parametros = cv2.aruco.DetectorParameters()
        # Esquinas con precisión subpíxel
        parametros.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        _detector = cv2.aruco.ArucoDetector(diccionario, parametros)

    return _detector


def detectar_marcadores(gris):
    """
    Regresa {id: (x, y)} con el centro de cada marcador del marco
    encontrado en la foto (solo los ids de geometria.ESQUINAS_UV).
    """

    esquinas, ids, _ = detector().detectMarkers(gris)

    if ids is None:
        return {}

    centros = {}

    for marcador, id_ in zip(esquinas, ids.flatten()):
        id_ = int(id_)
        if id_ in g.ESQUINAS_UV:
            centros[id_] = tuple(marcador[0].mean(axis=0))

    return centros


# =============================================
# HOMOGRAFÍA Y RECORTES
# =============================================

def homografia(centros):
    """Matriz 3x3: pixel de la foto -> pixel de la imagen enderezada."""

    ids = sorted(g.ESQUINAS_UV)
    origen = np.float32([centros[i] for i in ids])
    destino = np.float32([g.uv_a_pixel(*g.ESQUINAS_UV[i]) for i in ids])

    return cv2.getPerspectiveTransform(origen, destino)


def centro_panel_px(fila, columna):
    """Centro del hexágono (en 0,0) en la imagen enderezada."""
    return g.uv_a_pixel(*g.mundo_a_imagen(*g.panel_xy(fila, columna)))


def recortar(enderezada):
    """Los 16 recortes (índice = fila * 4 + columna), de LADO_RECORTE_PX."""

    lado = g.LADO_RECORTE_M * g.PIXELES_POR_METRO
    salida = g.LADO_RECORTE_PX
    escala = salida / lado

    recortes = []

    for _, fila, columna, _ in g.paneles():
        cx, cy = centro_panel_px(fila, columna)

        # Transformación afín: el centro del hexágono queda en el centro
        # del recorte (con precisión subpíxel, sin redondear)
        matriz = np.float32([
            [escala, 0, salida / 2 - cx * escala],
            [0, escala, salida / 2 - cy * escala],
        ])

        recortes.append(cv2.warpAffine(
            enderezada, matriz, (salida, salida),
            flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE,
        ))

    return recortes


# =============================================
# TODO JUNTO
# =============================================

@dataclass
class Resultado:
    ok: bool
    motivo: str = ""
    marcadores: dict = field(default_factory=dict)
    homografia: np.ndarray = None
    enderezada: np.ndarray = None
    recortes: list = field(default_factory=list)


def procesar(imagen, gris_salida=True):
    """
    Procesa una foto (BGR o gris). Si falta algún marcador regresa
    ok=False con el motivo (la foto no sirve para el diagnóstico).
    """

    gris = imagen if imagen.ndim == 2 else cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)

    centros = detectar_marcadores(gris)
    faltan = sorted(set(g.ESQUINAS_UV) - set(centros))

    if faltan:
        return Resultado(False, f"no se encontraron los marcadores {faltan}", centros)

    matriz = homografia(centros)
    lado = g.LADO_ENDEREZADA_PX

    fuente = gris if gris_salida else imagen
    enderezada = cv2.warpPerspective(
        fuente, matriz, (lado, lado),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )

    return Resultado(
        ok=True,
        marcadores=centros,
        homografia=matriz,
        enderezada=enderezada,
        recortes=recortar(enderezada),
    )


def dibujar_guia(enderezada):
    """Copia a color con el centro esperado y el recorte de cada hexágono."""

    vista = enderezada if enderezada.ndim == 3 else cv2.cvtColor(enderezada, cv2.COLOR_GRAY2BGR)
    vista = vista.copy()
    mitad = g.LADO_RECORTE_M * g.PIXELES_POR_METRO / 2

    for indice, fila, columna, _ in g.paneles():
        cx, cy = centro_panel_px(fila, columna)
        p1 = (int(cx - mitad), int(cy - mitad))
        p2 = (int(cx + mitad), int(cy + mitad))
        cv2.rectangle(vista, p1, p2, (0, 200, 255), 1)
        cv2.drawMarker(vista, (int(cx), int(cy)), (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
        cv2.putText(vista, str(indice), (p1[0] + 4, p1[1] + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

    for u, v in g.ESQUINAS_UV.values():
        x, y = g.uv_a_pixel(u, v)
        cv2.circle(vista, (int(x), int(y)), 6, (0, 255, 0), 2)

    return vista
