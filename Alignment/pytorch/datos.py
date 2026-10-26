"""
DATOS PARA PYTORCH - SOFIA (diagnóstico de alineación)

Lee los recortes de una sesión preparada (preparar_dataset.py) y los
entrega a PyTorch.

    - La primera vez lee los 32,000 PNG y guarda un caché
      (<sesión>/cache_recortes.npz, ~500 MB); las siguientes veces
      carga en segundos.
    - Entradas: recorte de 128x128 en gris, normalizado.
    - Salidas: (theta1, theta2) / 30°  -> valores entre -1 y 1.

AUMENTOS (solo en entrenamiento)
--------------------------------
Lo que el modelo debe medir es CUÁNTO se corrió la placa respecto al
centro del recorte, así que NO se usan traslaciones, rotaciones ni
cambios de escala (cambiarían la respuesta). Sí se usa:

    - Espejo horizontal: la placa se corre al otro lado -> theta1 cambia de signo.
    - Espejo vertical:   theta2 cambia de signo.
    - Brillo, contraste, gamma, ruido y desenfoque al azar
      (para que aguante la luz del robot real).
"""

import csv
import os
import sys

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

ALIGNMENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ALIGNMENT)

import geometria as g  # noqa: E402


ESCALA_ANGULO = g.LIMITE_GRADOS      # salida del modelo = ángulo / 30°
MEDIA, DESVIACION = 0.5, 0.25        # normalización de la imagen (0-1)


# =============================================
# CARGA (con caché)
# =============================================

def cargar_recortes(sesion):
    """
    Regresa un dict con:
        imagenes  uint8   (N, 128, 128)
        angulos   float32 (N, 2)      en grados
        conjunto  str     (N,)        train / val / test / referencia
        muestra   int     (N,)
        panel     int     (N,)
    """

    ruta_csv = os.path.join(sesion, "recortes.csv")
    ruta_cache = os.path.join(sesion, "cache_recortes.npz")

    if not os.path.isfile(ruta_csv):
        sys.exit(f"Falta {ruta_csv}: corre primero Alignment/herramientas/preparar_dataset.py")

    if os.path.isfile(ruta_cache) and os.path.getmtime(ruta_cache) >= os.path.getmtime(ruta_csv):
        datos = np.load(ruta_cache)
        return {clave: datos[clave] for clave in datos.files}

    with open(ruta_csv, newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    print(f"Leyendo {len(filas)} recortes (solo la primera vez)...")

    lado = g.LADO_RECORTE_PX
    imagenes = np.zeros((len(filas), lado, lado), np.uint8)

    for i, fila in enumerate(filas):
        imagen = cv2.imread(os.path.join(sesion, "recortes", fila["archivo"]), cv2.IMREAD_GRAYSCALE)
        if imagen is None:
            sys.exit(f"No se pudo leer {fila['archivo']}")
        imagenes[i] = imagen
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{len(filas)}")

    datos = {
        "imagenes": imagenes,
        "angulos": np.array([[float(f["theta1_deg"]), float(f["theta2_deg"])] for f in filas], np.float32),
        "conjunto": np.array([f["conjunto"] for f in filas]),
        "muestra": np.array([int(f["muestra"]) for f in filas]),
        "panel": np.array([int(f["panel"]) for f in filas]),
    }

    np.savez(ruta_cache, **datos)
    print(f"Caché guardado: {ruta_cache}")
    return datos


def seleccionar(datos, conjunto):
    """Imágenes y ángulos de un conjunto (train, val o test)."""
    filtro = datos["conjunto"] == conjunto
    return datos["imagenes"][filtro], datos["angulos"][filtro]


# =============================================
# DATASET
# =============================================

def a_tensor(imagen_uint8):
    """Recorte uint8 (H, W) -> tensor normalizado (1, H, W)."""
    x = imagen_uint8.astype(np.float32) / 255.0
    return torch.from_numpy((x - MEDIA) / DESVIACION)[None]


class DatasetRecortes(Dataset):

    def __init__(self, imagenes, angulos, aumentar=False, semilla=0):
        self.imagenes = imagenes
        self.angulos = angulos.astype(np.float32)
        self.aumentar = aumentar
        self.rng = np.random.default_rng(semilla)

    def __len__(self):
        return len(self.imagenes)

    def _aumentar(self, x, angulo):
        r = self.rng

        # Espejos (con el cambio de signo del ángulo correspondiente)
        if r.random() < 0.5:
            x = x[:, ::-1]
            angulo[0] = -angulo[0]
        if r.random() < 0.5:
            x = x[::-1, :]
            angulo[1] = -angulo[1]

        x = np.ascontiguousarray(x)

        # Luz: ganancia, desplazamiento y gamma
        x = np.clip(x * r.uniform(0.7, 1.3) + r.uniform(-0.1, 0.1), 0, 1)
        x = x ** r.uniform(0.8, 1.25)

        # Desenfoque (a veces) y ruido
        if r.random() < 0.3:
            x = cv2.GaussianBlur(x, (0, 0), r.uniform(0.3, 1.2))
        x = x + r.normal(0, r.uniform(0, 0.03), x.shape).astype(np.float32)

        return np.clip(x, 0, 1).astype(np.float32), angulo

    def __getitem__(self, i):
        x = self.imagenes[i].astype(np.float32) / 255.0
        angulo = self.angulos[i].copy()

        if self.aumentar:
            x, angulo = self._aumentar(x, angulo)

        x = torch.from_numpy((x - MEDIA) / DESVIACION)[None]
        y = torch.from_numpy(angulo / ESCALA_ANGULO)
        return x, y
