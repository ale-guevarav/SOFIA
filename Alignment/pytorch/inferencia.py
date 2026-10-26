"""
INFERENCIA - SOFIA (diagnóstico de alineación)

Carga un modelo entrenado y estima los ángulos de los 16 hexágonos.

    from inferencia import ModeloAlineacion
    modelo = ModeloAlineacion("Alignment/pytorch/entrenados/cnn_<sesión>/modelo.pt")
    theta1, theta2 = modelo.estimar(foto_bgr)          # foto completa (con ArUco)
    theta1, theta2 = modelo.estimar_recortes(recortes)  # 16 recortes ya hechos

Usa la GPU si hay; si no, la CPU.
"""

import os
import sys

import numpy as np
import torch

AQUI = os.path.dirname(os.path.abspath(__file__))
ALIGNMENT = os.path.dirname(AQUI)
sys.path.insert(0, ALIGNMENT)
sys.path.insert(0, AQUI)

import preprocesamiento as pp  # noqa: E402
from datos import DESVIACION, MEDIA  # noqa: E402
from modelos import crear_modelo  # noqa: E402


def dispositivo():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def cargar(ruta, equipo=None):
    """Regresa (modelo en modo evaluación, metadatos del checkpoint)."""
    equipo = equipo or dispositivo()
    punto = torch.load(ruta, map_location=equipo, weights_only=True)
    modelo = crear_modelo(punto["modelo"], preentrenada=False)   # los pesos vienen del archivo
    modelo.load_state_dict(punto["estado"])
    return modelo.to(equipo).eval(), punto


class ModeloAlineacion:

    def __init__(self, ruta, equipo=None):
        self.equipo = equipo or dispositivo()
        self.modelo, self.meta = cargar(ruta, self.equipo)
        self.escala = float(self.meta["escala_angulo"])

    @torch.inference_mode()
    def estimar_lote(self, imagenes_uint8):
        """(N, 128, 128) uint8 -> (N, 2) en grados."""
        x = torch.from_numpy(np.ascontiguousarray(imagenes_uint8)).to(self.equipo)
        x = ((x.float() / 255.0 - MEDIA) / DESVIACION)[:, None]
        with torch.autocast(self.equipo.type, enabled=self.equipo.type == "cuda"):
            y = self.modelo(x)
        return y.float().cpu().numpy() * self.escala

    def estimar_recortes(self, recortes):
        angulos = self.estimar_lote(np.stack(recortes))
        return angulos[:, 0], angulos[:, 1]

    def estimar(self, imagen_bgr):
        """Foto completa -> (theta1, theta2), o None si no se ven los 4 marcadores."""
        resultado = pp.procesar(imagen_bgr)
        if not resultado.ok:
            return None
        return self.estimar_recortes(resultado.recortes)
