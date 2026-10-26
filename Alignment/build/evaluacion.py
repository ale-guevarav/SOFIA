"""
EVALUACIÓN DEL DIAGNÓSTICO DE ALINEACIÓN - SOFIA

Métricas, gráficas y reporte, IGUALES para los tres métodos
(geométrico, CNN pequeña y ResNet18), para que se comparen tal cual.

Regresión (ángulos):
    - MAE, RMSE y sesgo por eje (theta1, theta2), en grados.
    - Error de la magnitud |theta|.
    - MAE por rango de desalineación real: 0-2°, 2-5°, 5-15°, >15°.

Clasificación (estado OK / REVISAR / DESALINEADO):
    - Exactitud, precisión, recall y F1 por estado, F1 macro.
    - "¿Necesita atención?" (REVISAR o DESALINEADO vs OK): precisión y recall.
    - Matriz de confusión.

Tiempo: ms por foto (preprocesamiento + estimación).
"""

import json
import os

import numpy as np

import geometria as g


ESTADOS = ["OK", "REVISAR", "DESALINEADO"]
RANGOS = [(0, 2), (2, 5), (5, 15), (15, 90)]


def estados(angulos):
    return np.array([g.desalineacion(t1, t2)[2] for t1, t2 in angulos])


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def calcular(real, estimado, tiempos_ms=None):
    """
    real, estimado: arreglos (N, 2) con (theta1, theta2) en grados.
    tiempos_ms: lista con el tiempo por foto (opcional).
    """

    real = np.asarray(real, float)
    estimado = np.asarray(estimado, float)
    error = estimado - real

    magnitud_real = np.hypot(real[:, 0], real[:, 1])
    magnitud_est = np.hypot(estimado[:, 0], estimado[:, 1])

    resultado = {"n": int(len(real))}

    # -----------------------------
    # REGRESIÓN
    # -----------------------------

    for eje, nombre in ((0, "theta1"), (1, "theta2")):
        resultado[nombre] = {
            "mae": _r(np.abs(error[:, eje]).mean()),
            "rmse": _r(np.sqrt((error[:, eje] ** 2).mean())),
            "sesgo": _r(error[:, eje].mean()),
            "p95": _r(np.percentile(np.abs(error[:, eje]), 95)),
        }

    resultado["mae_global"] = _r(np.abs(error).mean())
    resultado["rmse_global"] = _r(np.sqrt((error ** 2).mean()))
    resultado["mae_magnitud"] = _r(np.abs(magnitud_est - magnitud_real).mean())
    resultado["error_max"] = _r(np.abs(error).max())

    resultado["por_rango"] = {}
    for bajo, alto in RANGOS:
        sel = (magnitud_real >= bajo) & (magnitud_real < alto)
        resultado["por_rango"][f"{bajo}-{alto}"] = {
            "n": int(sel.sum()),
            "mae": _r(np.abs(error[sel]).mean()) if sel.any() else None,
        }

    # -----------------------------
    # CLASIFICACIÓN
    # -----------------------------

    e_real, e_est = estados(real), estados(estimado)

    matriz = [[int(((e_real == a) & (e_est == b)).sum()) for b in ESTADOS] for a in ESTADOS]

    clases = {}
    f1s = []
    for i, estado in enumerate(ESTADOS):
        tp = matriz[i][i]
        predichos = sum(matriz[k][i] for k in range(3))
        reales = sum(matriz[i])
        precision = tp / predichos if predichos else None
        recall = tp / reales if reales else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision and recall else 0.0 if precision is not None and recall is not None else None)
        if f1 is not None:
            f1s.append(f1)
        clases[estado] = {"n": reales, "precision": _r(precision), "recall": _r(recall), "f1": _r(f1)}

    atencion_real = e_real != "OK"
    atencion_est = e_est != "OK"
    tp = int((atencion_real & atencion_est).sum())

    resultado["clasificacion"] = {
        "exactitud": _r((e_real == e_est).mean()),
        "f1_macro": _r(np.mean(f1s)) if f1s else None,
        "por_estado": clases,
        "atencion": {
            "precision": _r(tp / atencion_est.sum()) if atencion_est.any() else None,
            "recall": _r(tp / atencion_real.sum()) if atencion_real.any() else None,
        },
        "matriz": {"etiquetas": ESTADOS, "valores": matriz},
    }

    if tiempos_ms:
        t = np.asarray(tiempos_ms, float)
        resultado["tiempo_ms_por_foto"] = {
            "promedio": _r(t.mean(), 2), "p95": _r(np.percentile(t, 95), 2), "fotos": int(len(t)),
        }

    return resultado


# =============================================
# GRÁFICAS Y REPORTE
# =============================================

def graficas(real, estimado, carpeta, titulo):

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    real = np.asarray(real, float)
    estimado = np.asarray(estimado, float)
    os.makedirs(carpeta, exist_ok=True)
    rutas = {}

    # 1. Real vs estimado
    fig, ejes = plt.subplots(1, 2, figsize=(10, 4.6))
    for eje, ax in enumerate(ejes):
        ax.scatter(real[:, eje], estimado[:, eje], s=4, alpha=0.4, color="#2E86C1")
        lim = g.LIMITE_GRADOS
        ax.plot([-lim, lim], [-lim, lim], color="#C0392B", lw=1)
        ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")
        ax.set_xlabel(f"theta{eje + 1} real (°)"); ax.set_ylabel(f"theta{eje + 1} estimado (°)")
        ax.grid(alpha=0.3)
    fig.suptitle(f"{titulo}: real vs estimado", fontweight="bold")
    fig.tight_layout()
    rutas["real_vs_estimado"] = os.path.join(carpeta, "real_vs_estimado.png")
    fig.savefig(rutas["real_vs_estimado"], dpi=130); plt.close(fig)

    # 2. Error contra magnitud real
    magnitud = np.hypot(real[:, 0], real[:, 1])
    error = np.abs(estimado - real).max(axis=1)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.scatter(magnitud, error, s=4, alpha=0.4, color="#2E86C1")
    for umbral in (g.UMBRAL_OK_GRADOS, g.UMBRAL_MAL_GRADOS):
        ax.axvline(umbral, color="#7F8C8D", ls="--", lw=1)
    ax.set_xlabel("|theta| real (°)"); ax.set_ylabel("error del peor eje (°)")
    ax.set_title(f"{titulo}: error según la desalineación", fontweight="bold")
    ax.grid(alpha=0.3); fig.tight_layout()
    rutas["error_vs_magnitud"] = os.path.join(carpeta, "error_vs_magnitud.png")
    fig.savefig(rutas["error_vs_magnitud"], dpi=130); plt.close(fig)

    # 3. Matriz de confusión
    e_real, e_est = estados(real), estados(estimado)
    matriz = np.array([[((e_real == a) & (e_est == b)).sum() for b in ESTADOS] for a in ESTADOS])
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    ax.imshow(matriz, cmap="Blues")
    ax.set_xticks(range(3), ESTADOS); ax.set_yticks(range(3), ESTADOS)
    ax.set_xlabel("estimado"); ax.set_ylabel("real")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, str(matriz[i, j]), ha="center", va="center",
                    color="white" if matriz[i, j] > matriz.max() / 2 else "black")
    ax.set_title(f"{titulo}: estados", fontweight="bold")
    fig.tight_layout()
    rutas["matriz_confusion"] = os.path.join(carpeta, "matriz_confusion.png")
    fig.savefig(rutas["matriz_confusion"], dpi=130); plt.close(fig)

    return rutas


def guardar(resultado, carpeta, titulo, detalles=None):
    """Guarda metricas.json y reporte.md en la carpeta."""

    os.makedirs(carpeta, exist_ok=True)
    datos = {"metodo": titulo, **(detalles or {}), "metricas": resultado}

    with open(os.path.join(carpeta, "metricas.json"), "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=2, ensure_ascii=False)

    r = resultado
    c = r["clasificacion"]
    lineas = [
        f"# Diagnóstico de alineación: {titulo}\n",
        *(f"- **{k}:** {v}" for k, v in (detalles or {}).items()),
        "",
        "## Ángulos\n",
        "| Eje | MAE (°) | RMSE (°) | Sesgo (°) | p95 (°) |",
        "| --- | --- | --- | --- | --- |",
        *(f"| {e} | {r[e]['mae']} | {r[e]['rmse']} | {r[e]['sesgo']} | {r[e]['p95']} |"
          for e in ("theta1", "theta2")),
        "",
        f"**MAE global: {r['mae_global']}°** · RMSE {r['rmse_global']}° · "
        f"error de magnitud {r['mae_magnitud']}° · error máximo {r['error_max']}° · "
        f"{r['n']} hexágonos\n",
        "| \\|θ\\| real | n | MAE (°) |",
        "| --- | --- | --- |",
        *(f"| {k}° | {v['n']} | {v['mae']} |" for k, v in r["por_rango"].items()),
        "",
        "## Estados\n",
        f"**Exactitud: {c['exactitud']}** · F1 macro {c['f1_macro']} · "
        f"¿necesita atención? precisión {c['atencion']['precision']}, recall {c['atencion']['recall']}\n",
        "| Estado | n | Precisión | Recall | F1 |",
        "| --- | --- | --- | --- | --- |",
        *(f"| {k} | {v['n']} | {v['precision']} | {v['recall']} | {v['f1']} |"
          for k, v in c["por_estado"].items()),
        "",
        "![Real vs estimado](real_vs_estimado.png)\n",
        "![Error vs magnitud](error_vs_magnitud.png)\n",
        "![Matriz de confusión](matriz_confusion.png)\n",
    ]

    if "tiempo_ms_por_foto" in r:
        t = r["tiempo_ms_por_foto"]
        lineas.insert(3, f"- **Tiempo por foto (16 hexágonos):** {t['promedio']} ms (p95 {t['p95']} ms)")

    with open(os.path.join(carpeta, "reporte.md"), "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(lineas))
