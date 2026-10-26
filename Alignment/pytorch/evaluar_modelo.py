"""
EVALUAR UN MODELO ENTRENADO - SOFIA (diagnóstico de alineación)

Mismas métricas, gráficas y reporte que el método geométrico
(evaluacion.py), para comparar tal cual. Se guarda en:

    Alignment/resultados/<modelo>_<sesión>_<conjunto>/

El tiempo se mide con el proceso COMPLETO (foto -> ArUco -> enderezar ->
16 recortes -> modelo), igual que en el geométrico, sobre unas fotos y
después de un calentamiento (la primera pasada por la GPU es lenta).

Uso (desde la carpeta SOFIA):
    python Alignment/pytorch/evaluar_modelo.py Alignment/pytorch/entrenados/cnn_<sesión>/modelo.pt
    python Alignment/pytorch/evaluar_modelo.py <modelo.pt> --conjunto val
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
ALIGNMENT = os.path.dirname(AQUI)
sys.path.insert(0, ALIGNMENT)
sys.path.insert(0, AQUI)

import evaluacion  # noqa: E402
import preprocesamiento as pp  # noqa: E402
from datos import cargar_recortes  # noqa: E402
from inferencia import ModeloAlineacion  # noqa: E402
from modelos import MODELOS  # noqa: E402

FOTOS_TIEMPO = 50
CALENTAMIENTO = 5


def medir_tiempo(modelo, sesion, muestras):
    """ms por foto con el proceso completo."""

    rutas = [os.path.join(sesion, "imagenes", f"{m:05d}.jpg") for m in muestras[:FOTOS_TIEMPO]]
    imagenes = [cv2.imread(r) for r in rutas]
    imagenes = [i for i in imagenes if i is not None]
    if not imagenes:
        return []

    for imagen in imagenes[:CALENTAMIENTO]:
        modelo.estimar(imagen)

    tiempos = []
    for imagen in imagenes:
        inicio = time.perf_counter()
        modelo.estimar(imagen)
        tiempos.append((time.perf_counter() - inicio) * 1000)
    return tiempos


def evaluar(ruta_modelo, conjunto="test", sesion=None):

    modelo = ModeloAlineacion(ruta_modelo)
    nombre = modelo.meta["modelo"]
    sesion = sesion or modelo.meta["sesion"]

    datos = cargar_recortes(sesion)
    if conjunto == "todos":
        filtro = datos["conjunto"] != "referencia"
    else:
        filtro = datos["conjunto"] == conjunto

    reales = datos["angulos"][filtro]
    imagenes = datos["imagenes"][filtro]

    estimados = np.concatenate([
        modelo.estimar_lote(imagenes[i:i + 512]) for i in range(0, len(imagenes), 512)
    ])

    muestras = sorted(set(datos["muestra"][filtro].tolist()))
    tiempos = medir_tiempo(modelo, sesion, muestras)

    metricas = evaluacion.calcular(reales, estimados, tiempos)

    titulo = MODELOS[nombre]
    carpeta = os.path.join(ALIGNMENT, "resultados", f"{nombre}_{os.path.basename(sesion)}_{conjunto}")

    evaluacion.graficas(reales, estimados, carpeta, titulo)
    evaluacion.guardar(metricas, carpeta, titulo, {
        "sesión": os.path.basename(sesion),
        "conjunto": conjunto,
        "fotos": len(muestras),
        "modelo": os.path.relpath(ruta_modelo, ALIGNMENT),
        "dispositivo": str(modelo.equipo),
        "época elegida": modelo.meta.get("epoca"),
    })

    c = metricas["clasificacion"]
    print(f"\n{titulo} · {conjunto} · {len(muestras)} fotos")
    print(f"MAE global {metricas['mae_global']}° · RMSE {metricas['rmse_global']}° · "
          f"θ1 {metricas['theta1']['mae']}° · θ2 {metricas['theta2']['mae']}° · "
          f"máx {metricas['error_max']}°")
    print("MAE por rango: " + ", ".join(
        f"{k}°: {v['mae']}" for k, v in metricas["por_rango"].items()))
    print(f"Estados: exactitud {c['exactitud']} · F1 macro {c['f1_macro']} · "
          f"atención: precisión {c['atencion']['precision']}, recall {c['atencion']['recall']}")
    if tiempos:
        print(f"Tiempo: {metricas['tiempo_ms_por_foto']['promedio']} ms por foto ({modelo.equipo})")
    print(f"\nReporte: {carpeta}")
    return metricas


def main():
    parser = argparse.ArgumentParser(description="Evalúa un modelo entrenado")
    parser.add_argument("modelo", help="ruta del modelo.pt")
    parser.add_argument("--conjunto", default="test", choices=["train", "val", "test", "todos"])
    parser.add_argument("--sesion", help="otra sesión (por defecto, la del entrenamiento)")
    args = parser.parse_args()

    sesion = os.path.abspath(args.sesion) if args.sesion else None
    evaluar(os.path.abspath(args.modelo), args.conjunto, sesion)


if __name__ == "__main__":
    main()
