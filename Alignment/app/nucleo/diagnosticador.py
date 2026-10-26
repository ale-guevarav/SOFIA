"""
DIAGNOSTICADOR Y MÉTODO HÍBRIDO - SOFIA (diagnóstico de alineación)

Junta los dos métodos para quedarse con lo mejor de cada uno
(ver results/COMPARACION.md):

    - El GEOMÉTRICO es el más preciso con ángulos chicos (0-5°), justo
      donde están los umbrales OK / REVISAR / DESALINEADO.
    - La CNN no tiene errores catastróficos y es mejor con ángulos grandes.

REGLA, para cada hexágono:

    1. Se estiman los ángulos con los dos métodos.
    2. Si difieren más de DESACUERDO_GRADOS en algún eje, el geométrico
       probablemente se confundió: se usa la CNN y el hexágono se marca
       como "desacuerdo" (conviene revisarlo).
    3. Si están de acuerdo y la CNN dice que el hexágono está cerca de 0,0
       (|theta| <= ZONA_GEOMETRICO_GRADOS), se usa el geométrico.
    4. Si no, se usa la CNN.

La CNN decide la zona (paso 3) porque nunca se equivoca por mucho.

DIAGNOSTICADOR
--------------
Diagnosticador(metodo) es lo que usan la app y las evaluaciones:

    diag = Diagnosticador("hibrido")          # o "geometrico" / "cnn"
    diag.fijar_referencia(foto_en_cero)       # opcional, mejora el geométrico
    d = diag.analizar(foto_bgr)
    d.theta1, d.theta2, d.estado, d.fuente, d.desacuerdo, d.tiempos_ms

Si no está PyTorch o no hay modelo entrenado, "cnn" e "hibrido"
regresan al geométrico y lo avisan en `aviso` (así el equipo puede
usarlo sin GPU).
"""

import os
import time
from dataclasses import dataclass, field

import numpy as np

import geometria as g
import preprocesamiento as pp
import rutas
from metodo_geometrico import MetodoGeometrico


DESACUERDO_GRADOS = 2.0
ZONA_GEOMETRICO_GRADOS = 6.0

METODOS = {
    "geometrico": "Geométrico",
    "cnn": "CNN pequeña",
    "hibrido": "Híbrido",
}

def buscar_modelo():
    """El modelo publicado (results/modelo/cnn.pt); si no está, el último entrenado en esta PC."""
    if os.path.isfile(rutas.MODELO_PUBLICADO):
        return rutas.MODELO_PUBLICADO
    return rutas.ultima_cnn_entrenada()


# =============================================
# FUSIÓN
# =============================================

def fusionar(geo, cnn):
    """
    geo, cnn: arreglos (16, 2) en grados.
    Regresa (angulos (16, 2), fuente [16 str], desacuerdo bool (16,)).
    """

    geo = np.asarray(geo, float)
    cnn = np.asarray(cnn, float)

    diferencia = np.abs(geo - cnn).max(axis=1)
    desacuerdo = diferencia > DESACUERDO_GRADOS
    cerca_de_cero = np.hypot(cnn[:, 0], cnn[:, 1]) <= ZONA_GEOMETRICO_GRADOS

    usar_geo = cerca_de_cero & ~desacuerdo
    angulos = np.where(usar_geo[:, None], geo, cnn)
    fuente = ["geo" if u else "cnn" for u in usar_geo]
    return angulos, fuente, desacuerdo


# =============================================
# RESULTADO
# =============================================

@dataclass
class Diagnostico:
    ok: bool
    motivo: str = ""
    metodo: str = ""                    # el que se usó de verdad
    theta1: np.ndarray = None           # (16,) grados
    theta2: np.ndarray = None
    magnitud: list = field(default_factory=list)
    porcentaje: list = field(default_factory=list)
    estado: list = field(default_factory=list)
    fuente: list = field(default_factory=list)          # "geo" / "cnn" por hexágono
    desacuerdo: np.ndarray = None       # (16,) bool (solo híbrido)
    geo: np.ndarray = None              # (16, 2) estimación de cada método
    cnn: np.ndarray = None
    tiempos_ms: dict = field(default_factory=dict)
    enderezada: np.ndarray = None       # foto enderezada (gris)

    def conteo(self):
        return {e: self.estado.count(e) for e in ("OK", "REVISAR", "DESALINEADO")}


# =============================================
# DIAGNOSTICADOR
# =============================================

class Diagnosticador:

    def __init__(self, metodo="hibrido", ruta_modelo=None):
        if metodo not in METODOS:
            raise ValueError(f"Método desconocido: {metodo}")

        self.metodo_pedido = metodo
        self.metodo = metodo
        self.aviso = ""
        self.geometrico = MetodoGeometrico(None)
        self.referencia = False
        self.cnn = None
        self.ruta_modelo = None

        if metodo != "geometrico":
            self._cargar_cnn(ruta_modelo or buscar_modelo())

    def _cargar_cnn(self, ruta):
        if not ruta or not os.path.isfile(ruta):
            self._sin_cnn("no hay modelo (results/modelo/cnn.pt)")
            return
        try:
            from inferencia import ModeloAlineacion
            self.cnn = ModeloAlineacion(ruta)
            self.ruta_modelo = ruta
        except ImportError as error:
            self._sin_cnn(f"PyTorch no está instalado ({error.name})")
        except Exception as error:   # modelo dañado, versión distinta, etc.
            self._sin_cnn(f"no se pudo cargar el modelo ({error})")

    def _sin_cnn(self, razon):
        self.metodo = "geometrico"
        self.aviso = f"{razon}: se usa el método geométrico"

    @property
    def dispositivo(self):
        return str(self.cnn.equipo) if self.cnn is not None else "cpu"

    def fijar_referencia(self, imagen):
        """Foto con todo en 0,0: el geométrico mide desde ahí. Regresa (ok, motivo)."""
        resultado = pp.procesar(imagen)
        if not resultado.ok:
            return False, resultado.motivo
        self.geometrico = MetodoGeometrico(resultado.enderezada)
        self.referencia = True
        return True, ""

    def quitar_referencia(self):
        self.geometrico = MetodoGeometrico(None)
        self.referencia = False

    def analizar(self, imagen):

        tiempos = {}
        inicio = time.perf_counter()

        resultado = pp.procesar(imagen)
        tiempos["preprocesado"] = (time.perf_counter() - inicio) * 1000

        if not resultado.ok:
            return Diagnostico(False, resultado.motivo, self.metodo, tiempos_ms=tiempos)

        geo = cnn = None

        if self.metodo in ("geometrico", "hibrido"):
            t = time.perf_counter()
            geo = np.c_[self.geometrico.estimar(resultado.enderezada)]
            tiempos["geometrico"] = (time.perf_counter() - t) * 1000

        if self.metodo in ("cnn", "hibrido"):
            t = time.perf_counter()
            cnn = np.c_[self.cnn.estimar_recortes(resultado.recortes)]
            tiempos["cnn"] = (time.perf_counter() - t) * 1000

        if self.metodo == "hibrido":
            angulos, fuente, desacuerdo = fusionar(geo, cnn)
        elif self.metodo == "cnn":
            angulos, fuente, desacuerdo = cnn, ["cnn"] * 16, np.zeros(16, bool)
        else:
            angulos, fuente, desacuerdo = geo, ["geo"] * 16, np.zeros(16, bool)

        tiempos["total"] = (time.perf_counter() - inicio) * 1000

        evaluados = [g.desalineacion(t1, t2) for t1, t2 in angulos]

        return Diagnostico(
            ok=True,
            metodo=self.metodo,
            theta1=angulos[:, 0],
            theta2=angulos[:, 1],
            magnitud=[e[0] for e in evaluados],
            porcentaje=[e[1] for e in evaluados],
            estado=[e[2] for e in evaluados],
            fuente=fuente,
            desacuerdo=desacuerdo,
            geo=geo,
            cnn=cnn,
            tiempos_ms=tiempos,
            enderezada=resultado.enderezada,
        )
