"""
CÁMARAS - SOFIA

Lista las cámaras conectadas con su nombre del sistema y las abre de forma
que el número de la lista coincida con el que abre OpenCV:

    - Windows: nombres de DirectShow (paquete pygrabber) y se abren con
      DirectShow (cv2.CAP_DSHOW), así el orden es el mismo.
    - Linux: /sys/class/video4linux (nombre de cada /dev/videoN; se saltan
      los nodos de metadatos que crea cada cámara).
    - Sin eso (o en otro sistema): se prueban 0..MAX_PRUEBA-1 y se llaman
      "Cámara N".

Lo usan la detección de poses (vision_worker), el menú Alineación y sus
ventanas (alineacion_worker).
"""

import glob
import os
import sys

import cv2

MAX_PRUEBA = 6
ES_WINDOWS = sys.platform == "win32"


def abrir(indice):
    """Abre la cámara 'indice' de listar()."""
    if ES_WINDOWS:
        camara = cv2.VideoCapture(indice, cv2.CAP_DSHOW)
        if camara.isOpened():
            return camara
        camara.release()
    return cv2.VideoCapture(indice)


def _probar(ocupadas=()):
    encontradas = []
    for indice in range(MAX_PRUEBA):
        if indice in ocupadas:
            encontradas.append((indice, f"Cámara {indice}"))
            continue
        camara = abrir(indice)
        if camara.isOpened():
            encontradas.append((indice, f"Cámara {indice}"))
        camara.release()
    return encontradas


def _linux():
    encontradas = []
    for ruta in glob.glob("/sys/class/video4linux/video*"):
        try:
            indice = int(os.path.basename(ruta)[len("video"):])
        except ValueError:
            continue
        try:
            with open(os.path.join(ruta, "index")) as f:
                if int(f.read().strip()) != 0:      # nodo de metadatos, no de imagen
                    continue
        except (OSError, ValueError):
            pass
        try:
            with open(os.path.join(ruta, "name")) as f:
                nombre = f.read().strip()
        except OSError:
            nombre = f"Cámara {indice}"
        encontradas.append((indice, nombre))
    return sorted(encontradas)


def listar(ocupadas=()):
    """
    [(indice, nombre)] de las cámaras conectadas. 'ocupadas': índices que ya
    están abiertos (no se prueban, para no pelear por ellos).
    """
    if ES_WINDOWS:
        try:
            from pygrabber.dshow_graph import FilterGraph
            nombres = FilterGraph().get_input_devices()
            return [(i, n) for i, n in enumerate(nombres)]
        except Exception:
            return _probar(ocupadas)
    if sys.platform.startswith("linux"):
        encontradas = _linux()
        if encontradas:
            return encontradas
    return _probar(ocupadas)
