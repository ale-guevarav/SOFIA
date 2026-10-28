"""
COMPARAR RESULTADOS - SOFIA (diagnóstico de alineación)

Junta todos los Alignment/results/evaluaciones/*/metricas.json en una tabla y una
gráfica, para poner lado a lado el método geométrico y los modelos.

Sale en:
    Alignment/results/evaluaciones/comparacion.md
    Alignment/results/evaluaciones/comparacion.png

Uso (desde la carpeta SOFIA):
    python Alignment/build/comparar_resultados.py              (solo test)
    python Alignment/build/comparar_resultados.py --conjunto val
    python Alignment/build/comparar_resultados.py --sesion todas     (mezcla sesiones)

Por defecto solo compara los resultados de la ÚLTIMA sesión de Webots,
para no mezclar datasets distintos (por ejemplo, antes y después del PROTO).
"""

import argparse
import glob
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "app", "nucleo"))
sys.path.insert(0, AQUI)

import rutas  # noqa: E402

RESULTADOS = rutas.EVALUACIONES

ORDEN = ["Método geométrico", "CNN pequeña", "ResNet18 preentrenada", "Método híbrido"]


def leer(conjunto, sesion=None):
    filas = []
    for ruta in sorted(glob.glob(os.path.join(RESULTADOS, "*", "metricas.json"))):
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
        if datos.get("conjunto") != conjunto:
            continue
        if sesion and datos.get("sesión") != sesion:
            continue
        datos["carpeta"] = os.path.basename(os.path.dirname(ruta))
        filas.append(datos)
    filas.sort(key=lambda d: (ORDEN.index(d["metodo"]) if d["metodo"] in ORDEN else 99, d["carpeta"]))
    return filas


def tabla(filas):
    rangos = list(filas[0]["metricas"]["por_rango"])
    encabezado = (["Método", "Sesión", "MAE (°)", "RMSE (°)", "p95 θ1/θ2 (°)", "Error máx (°)"]
                  + [f"MAE {r}°" for r in rangos]
                  + ["Exactitud", "F1 macro", "Recall atención", "ms/foto"])
    lineas = ["| " + " | ".join(encabezado) + " |", "|" + " --- |" * len(encabezado)]

    for d in filas:
        m = d["metricas"]
        c = m["clasificacion"]
        t = m.get("tiempo_ms_por_foto", {}).get("promedio", "-")
        celdas = ([d["metodo"], d.get("sesión", ""), m["mae_global"], m["rmse_global"],
                   f"{m['theta1']['p95']} / {m['theta2']['p95']}", m["error_max"]]
                  + [m["por_rango"][r]["mae"] for r in rangos]
                  + [c["exactitud"], c["f1_macro"], c["atencion"]["recall"], t])
        lineas.append("| " + " | ".join(str(x) for x in celdas) + " |")
    return lineas, rangos


def grafica(filas, rangos, ruta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    colores = ["#7F8C8D", "#2E86C1", "#C0392B", "#27AE60", "#8E44AD"]
    ancho = 0.8 / len(filas)
    x = np.arange(len(rangos))

    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw={"width_ratios": [2, 1]})
    for i, d in enumerate(filas):
        valores = [d["metricas"]["por_rango"][r]["mae"] or 0 for r in rangos]
        a.bar(x + (i - (len(filas) - 1) / 2) * ancho, valores, ancho,
              label=d["metodo"], color=colores[i % len(colores)])
    a.set_xticks(x, [f"{r}°" for r in rangos])
    a.set_xlabel("|θ| real"); a.set_ylabel("MAE (°)"); a.set_title("Error por rango", fontweight="bold")
    a.grid(axis="y", alpha=0.3); a.legend()

    nombres = [d["metodo"].replace(" preentrenada", "") for d in filas]
    b.bar(nombres, [d["metricas"]["clasificacion"]["exactitud"] for d in filas],
          color=[colores[i % len(colores)] for i in range(len(filas))])
    b.set_ylim(0.8, 1.0); b.set_title("Exactitud de estados", fontweight="bold")
    b.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(ruta, dpi=130); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Compara los resultados guardados")
    parser.add_argument("--conjunto", default="test", choices=["train", "val", "test", "todos"])
    parser.add_argument("--sesion", help="nombre de la sesión, o 'todas' (por defecto, la última)")
    args = parser.parse_args()

    if args.sesion == "todas":
        sesion = None
    elif args.sesion:
        sesion = os.path.basename(os.path.normpath(args.sesion))
    else:
        sesion = os.path.basename(rutas.ultima_sesion())

    filas = leer(args.conjunto, sesion)
    if not filas:
        raise SystemExit(f"No hay resultados de '{args.conjunto}' de la sesión {sesion or '(todas)'} en {RESULTADOS}")

    lineas, rangos = tabla(filas)
    grafica(filas, rangos, os.path.join(RESULTADOS, "comparacion.png"))

    texto = [f"# Comparación de métodos ({args.conjunto})\n", *lineas, "",
             "![Comparación](comparacion.png)\n"]
    with open(os.path.join(RESULTADOS, "comparacion.md"), "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(texto))

    print("\n".join(lineas))
    print(f"\nGuardado en {os.path.join(RESULTADOS, 'comparacion.md')}")


if __name__ == "__main__":
    main()
