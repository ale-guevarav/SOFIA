"""
DATOS PARA PYTORCH - SOFIA (diagnóstico de alineación)

Lee los recortes de una sesión preparada (preparar_dataset.py) y los
entrega a PyTorch.

    - La primera vez lee los PNG (16 por foto) y guarda un caché
      (<sesión>/cache_recortes.npz, ~260 MB por cada 1000 fotos); las siguientes veces
      carga en segundos.
    - Entradas: recorte de 128x128 en gris, normalizado.
    - Salidas: (theta1, theta2) / 30°  -> valores entre -1 y 1.

Con GPU, CargadorGPU (abajo) sube todo a la GPU y hace los aumentos ahí.

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

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "app", "nucleo"))
sys.path.insert(0, AQUI)

import geometria as g  # noqa: E402
from modelos import DESVIACION, ESCALA_ANGULO, MEDIA  # noqa: E402,F401


# ESCALA_ANGULO, MEDIA y DESVIACION vienen de app/nucleo/modelos.py:
# la app normaliza exactamente igual que el entrenamiento.


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
        sys.exit(f"Falta {ruta_csv}: corre primero Alignment/build/preparar_dataset.py")

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


# =============================================
# TODO EN LA GPU (rápido con datasets grandes)
# =============================================

def aumentar_lote(x, y, generador):
    """
    Los mismos aumentos que DatasetRecortes, pero para un lote entero
    que ya está en la GPU. x: (B, 1, H, W) en 0-1; y: (B, 2) ángulo / 30°.
    """
    lote = x.shape[0]
    equipo = x.device

    def al_azar(bajo, alto, forma):
        return torch.empty(forma, device=equipo).uniform_(bajo, alto, generator=generador)

    # Espejos (con el cambio de signo del ángulo correspondiente)
    horizontal = torch.rand(lote, device=equipo, generator=generador) < 0.5
    x = torch.where(horizontal[:, None, None, None], x.flip(-1), x)
    y[:, 0] = torch.where(horizontal, -y[:, 0], y[:, 0])

    vertical = torch.rand(lote, device=equipo, generator=generador) < 0.5
    x = torch.where(vertical[:, None, None, None], x.flip(-2), x)
    y[:, 1] = torch.where(vertical, -y[:, 1], y[:, 1])

    # Luz: ganancia, desplazamiento y gamma
    forma = (lote, 1, 1, 1)
    x = (x * al_azar(0.7, 1.3, forma) + al_azar(-0.1, 0.1, forma)).clamp(0, 1)
    x = x.pow(al_azar(0.8, 1.25, forma))

    # Desenfoque (a 30 % del lote, con una sigma al azar para ese lote)
    sigma = float(al_azar(0.3, 1.2, (1,)))
    radio = 3
    t = torch.arange(-radio, radio + 1, device=equipo, dtype=x.dtype)
    nucleo = torch.exp(-t ** 2 / (2 * sigma ** 2))
    nucleo = (nucleo[:, None] * nucleo[None, :]) / nucleo.sum() ** 2
    borroso = torch.nn.functional.conv2d(
        torch.nn.functional.pad(x, (radio,) * 4, mode="reflect"), nucleo[None, None])
    desenfocar = torch.rand(lote, device=equipo, generator=generador) < 0.3
    x = torch.where(desenfocar[:, None, None, None], borroso, x)

    # Ruido
    ruido = torch.randn(x.shape, device=equipo, generator=generador)
    x = (x + ruido * al_azar(0.0, 0.03, forma)).clamp(0, 1)

    return x, y


class CargadorGPU:
    """
    Reemplaza al DataLoader: sube TODOS los recortes a la GPU una vez
    (uint8, ~16 KB por recorte; 10 000 fotos ~ 2.6 GB) y arma cada lote
    ahí mismo, con los aumentos en la GPU. Así el CPU deja de ser el
    cuello de botella (antes cada época tardaba por los aumentos).
    """

    def __init__(self, imagenes, angulos, equipo, lote, aumentar=False,
                 barajar=False, descartar_ultimo=False, semilla=0):
        self.imagenes = torch.from_numpy(np.ascontiguousarray(imagenes)).to(equipo)
        self.angulos = torch.from_numpy(angulos.astype(np.float32) / ESCALA_ANGULO).to(equipo)
        self.equipo = equipo
        self.lote = lote
        self.aumentar = aumentar
        self.barajar = barajar
        self.descartar_ultimo = descartar_ultimo
        self.generador = torch.Generator(device=equipo)
        self.generador.manual_seed(semilla)

    def __len__(self):
        n = len(self.imagenes)
        return n // self.lote if self.descartar_ultimo else -(-n // self.lote)

    def __iter__(self):
        n = len(self.imagenes)
        if self.barajar:
            orden = torch.randperm(n, device=self.equipo, generator=self.generador)
        else:
            orden = torch.arange(n, device=self.equipo)

        for i in range(len(self)):
            indices = orden[i * self.lote:(i + 1) * self.lote]
            x = self.imagenes[indices].unsqueeze(1).float() / 255.0
            y = self.angulos[indices].clone()
            if self.aumentar:
                x, y = aumentar_lote(x, y, self.generador)
            yield (x - MEDIA) / DESVIACION, y
