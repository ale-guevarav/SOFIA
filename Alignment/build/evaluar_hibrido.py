"""
EVALUAR EL MÉTODO HÍBRIDO - SOFIA (diagnóstico de alineación)

Corre geométrico + CNN sobre las MISMAS fotos, aplica la regla del
híbrido y guarda métricas, gráficas y reporte igual que los otros:

    Alignment/results/evaluaciones/hibrido_<sesión>_<conjunto>/

Además dice qué tan útil fue la marca de "desacuerdo": de los
hexágonos marcados, cuántos eran de verdad un error grande del geométrico.

Uso (desde la carpeta SOFIA):
    python Alignment/build/evaluar_hibrido.py                       (última sesión, test)
    python Alignment/build/evaluar_hibrido.py --conjunto val
    python Alignment/build/evaluar_hibrido.py --modelo <modelo.pt>
"""

import argparse
import csv
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "app", "nucleo"))
sys.path.insert(0, AQUI)

import diagnosticador as mh  # noqa: E402
import evaluacion  # noqa: E402
import rutas  # noqa: E402


def main():

    parser = argparse.ArgumentParser(description="Evalúa el método híbrido")
    parser.add_argument("sesion", nargs="?", help="carpeta de la sesión (por defecto, la última)")
    parser.add_argument("--conjunto", default="test", choices=["train", "val", "test", "todos"])
    parser.add_argument("--modelo", help="modelo.pt de la CNN (por defecto, el publicado o el último)")
    args = parser.parse_args()

    sesion = os.path.abspath(args.sesion) if args.sesion else rutas.ultima_sesion()
    ruta_csv = os.path.join(sesion, "recortes.csv")
    if not os.path.isfile(ruta_csv):
        sys.exit(f"Falta {ruta_csv}: corre primero preparar_dataset.py")

    diag = mh.Diagnosticador("hibrido", args.modelo)
    if diag.metodo != "hibrido":
        sys.exit(f"No se puede evaluar el híbrido: {diag.aviso}")
    print(f"Modelo: {diag.ruta_modelo} ({diag.dispositivo})")

    ok, motivo = diag.fijar_referencia(cv2.imread(os.path.join(sesion, "imagenes", "00000.jpg")))
    if not ok:
        sys.exit(f"Foto de referencia 00000.jpg: {motivo}")

    with open(ruta_csv, newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    por_foto = {}
    for f in filas:
        if f["conjunto"] == "referencia" or (args.conjunto != "todos" and f["conjunto"] != args.conjunto):
            continue
        por_foto.setdefault(int(f["muestra"]), np.zeros((16, 2)))[int(f["panel"])] = (
            float(f["theta1_deg"]), float(f["theta2_deg"]))

    print(f"Sesión {os.path.basename(sesion)} · conjunto {args.conjunto} · {len(por_foto)} fotos")

    # Calentamiento de la GPU (la primera pasada es lenta)
    primera = cv2.imread(os.path.join(sesion, "imagenes", f"{min(por_foto):05d}.jpg"))
    for _ in range(3):
        diag.analizar(primera)

    reales, hibrido, geo, cnn, desacuerdos, fuentes, tiempos = [], [], [], [], [], [], []

    for k, (muestra, angulos) in enumerate(sorted(por_foto.items())):
        d = diag.analizar(cv2.imread(os.path.join(sesion, "imagenes", f"{muestra:05d}.jpg")))
        if not d.ok:
            print(f"  foto {muestra}: {d.motivo}")
            continue

        reales.append(angulos)
        hibrido.append(np.c_[d.theta1, d.theta2])
        geo.append(d.geo)
        cnn.append(d.cnn)
        desacuerdos.append(d.desacuerdo)
        fuentes += d.fuente
        tiempos.append(d.tiempos_ms["total"])

        if (k + 1) % 100 == 0:
            print(f"  {k + 1}/{len(por_foto)}")

    reales = np.concatenate(reales)
    hibrido = np.concatenate(hibrido)
    geo = np.concatenate(geo)
    cnn = np.concatenate(cnn)
    desacuerdos = np.concatenate(desacuerdos)

    metricas = evaluacion.calcular(reales, hibrido, tiempos)

    # Qué tan útil fue la marca de desacuerdo
    error_geo = np.abs(geo - reales).max(axis=1)
    geo_malo = error_geo > mh.DESACUERDO_GRADOS
    marcados = int(desacuerdos.sum())
    atrapados = int((desacuerdos & geo_malo).sum())

    extra = {
        "hexágonos con geométrico": f"{fuentes.count('geo')} de {len(fuentes)}",
        "desacuerdos marcados": marcados,
        "desacuerdos que eran error del geométrico": f"{atrapados} de {marcados}",
        "errores del geométrico (> umbral) atrapados": f"{atrapados} de {int(geo_malo.sum())}",
        "umbral de desacuerdo (°)": mh.DESACUERDO_GRADOS,
        "zona del geométrico (°)": mh.ZONA_GEOMETRICO_GRADOS,
    }

    carpeta = os.path.join(rutas.EVALUACIONES, f"hibrido_{os.path.basename(sesion)}_{args.conjunto}")
    titulo = "Método híbrido"

    evaluacion.graficas(reales, hibrido, carpeta, titulo)
    evaluacion.guardar(metricas, carpeta, titulo, {
        "sesión": os.path.basename(sesion),
        "conjunto": args.conjunto,
        "fotos": len(tiempos),
        "modelo": os.path.relpath(diag.ruta_modelo, rutas.ALIGNMENT),
        "dispositivo": diag.dispositivo,
        **extra,
    })

    # Referencia: los dos métodos solos en estas mismas fotos
    mae = lambda est: round(float(np.abs(est - reales).mean()), 3)  # noqa: E731
    c = metricas["clasificacion"]
    print(f"\nMAE  híbrido {metricas['mae_global']}° · geométrico {mae(geo)}° · CNN {mae(cnn)}°")
    print(f"Error máx híbrido {metricas['error_max']}° · RMSE {metricas['rmse_global']}°")
    print("MAE por rango: " + ", ".join(f"{k}°: {v['mae']}" for k, v in metricas["por_rango"].items()))
    print(f"Estados: exactitud {c['exactitud']} · F1 macro {c['f1_macro']} · "
          f"atención: precisión {c['atencion']['precision']}, recall {c['atencion']['recall']}")
    for k, v in extra.items():
        print(f"{k}: {v}")
    print(f"Tiempo: {metricas['tiempo_ms_por_foto']['promedio']} ms por foto")
    print(f"\nReporte: {carpeta}")


if __name__ == "__main__":
    main()
