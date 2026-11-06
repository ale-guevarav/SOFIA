"""
MODELOS - SOFIA (diagnóstico de alineación)

Los dos reciben un recorte de 128x128 (1 canal) y regresan
(theta1, theta2) / 30°.

    cnn        CNN pequeña entrenada desde cero (~1.3 M parámetros).
    resnet18   ResNet18 preentrenada en ImageNet, ajustada (~13 M).

DETALLE IMPORTANTE: SIN PROMEDIO GLOBAL AL FINAL
------------------------------------------------
Las CNN de clasificación terminan con un "promedio global" que tira la
posición de las cosas en la imagen (sirve para decir QUÉ hay, no DÓNDE).
Aquí la respuesta es justamente DÓNDE quedó la placa respecto al centro
del recorte, así que en los dos modelos el mapa final (4x4) se aplana y
pasa completo a la capa densa: el modelo conserva la posición.
"""

import torch
from torch import nn

import geometria as g

# Normalización compartida por el entrenamiento (build/) y la app
ESCALA_ANGULO = g.LIMITE_GRADOS      # salida del modelo = ángulo / 30°
MEDIA, DESVIACION = 0.5, 0.25        # imagen 0-1 -> (x - MEDIA) / DESVIACION


def _bloque(entrada, salida):
    return nn.Sequential(
        nn.Conv2d(entrada, salida, 3, padding=1, bias=False),
        nn.BatchNorm2d(salida),
        nn.ReLU(inplace=True),
        nn.Conv2d(salida, salida, 3, padding=1, bias=False),
        nn.BatchNorm2d(salida),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class CNNPequena(nn.Module):
    """5 bloques convolucionales: 128 -> 64 -> 32 -> 16 -> 8 -> 4."""

    def __init__(self):
        super().__init__()
        self.extractor = nn.Sequential(
            _bloque(1, 32),
            _bloque(32, 64),
            _bloque(64, 96),
            _bloque(96, 128),
            _bloque(128, 128),
        )
        self.cabeza = nn.Sequential(
            nn.Flatten(),                    # 128 x 4 x 4 = 2048 (conserva la posición)
            nn.Linear(128 * 4 * 4, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(256, 2),
        )

    def forward(self, x):
        return self.cabeza(self.extractor(x))


class ResNet18Alineacion(nn.Module):
    """ResNet18 de torchvision con la cabeza cambiada para regresar 2 ángulos."""

    def __init__(self, preentrenada=True):
        super().__init__()
        from torchvision import models

        pesos = models.ResNet18_Weights.DEFAULT if preentrenada else None
        red = models.resnet18(weights=pesos)

        red.avgpool = nn.Identity()          # sin promedio global (ver arriba)
        red.fc = nn.Sequential(
            nn.Linear(512 * 4 * 4, 256),     # mapa final 512 x 4 x 4 con entrada de 128
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(256, 2),
        )
        self.red = red

        # Normalización de ImageNet (la red preentrenada la espera)
        self.register_buffer("media_imagenet", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("desv_imagenet", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

    def forward(self, x):
        # Gris normalizado -> 0-1 -> 3 canales -> normalización de ImageNet
        x = (x * DESVIACION + MEDIA).repeat(1, 3, 1, 1)
        x = (x - self.media_imagenet) / self.desv_imagenet
        return self.red(x)


MODELOS = {
    "cnn": "CNN pequeña",
    "resnet18": "ResNet18 preentrenada",
}


def crear_modelo(nombre, preentrenada=True):
    if nombre == "cnn":
        return CNNPequena()
    if nombre == "resnet18":
        return ResNet18Alineacion(preentrenada=preentrenada)
    raise ValueError(f"Modelo desconocido: {nombre} (opciones: {', '.join(MODELOS)})")


def contar_parametros(modelo):
    return sum(p.numel() for p in modelo.parameters())
