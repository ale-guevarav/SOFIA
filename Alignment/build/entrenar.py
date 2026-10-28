"""
ENTRENAR - SOFIA (diagnóstico de alineación)

Entrena la CNN pequeña o la ResNet18 con los recortes de una sesión y al
final la evalúa en test (igual que el método geométrico).

    - Optimizador AdamW con OneCycle (sube y baja el learning rate).
    - Precisión mixta (AMP) en la GPU: más rápido y usa menos memoria.
    - Pérdida SmoothL1 sobre ángulo / 30°.
    - Cada época se mide el MAE en val (grados) y se guarda el MEJOR.

Sale en Alignment/build/entrenados/<modelo>_<sesión>/:
    modelo.pt       pesos + datos para usarlo (inferencia.py)
    historial.csv   pérdida y MAE por época
    curvas.png      gráfica del historial

Uso (desde la carpeta SOFIA):
    python Alignment/build/entrenar.py --modelo cnn
    python Alignment/build/entrenar.py --modelo resnet18
    python Alignment/build/entrenar.py --modelo cnn --epocas 60 --lote 256
"""

import argparse
import csv
import os
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "app", "nucleo"))
sys.path.insert(0, AQUI)

import geometria as g  # noqa: E402
import rutas  # noqa: E402
from dataset_torch import CargadorGPU, DatasetRecortes, cargar_recortes, seleccionar  # noqa: E402
from modelos import DESVIACION, ESCALA_ANGULO, MEDIA, MODELOS, contar_parametros, crear_modelo  # noqa: E402

POR_DEFECTO = {
    "cnn": {"epocas": 25, "lr": 2e-3},        # con ~10 000 fotos; con pocas fotos, más épocas
    "resnet18": {"epocas": 25, "lr": 1e-3},
}


@torch.no_grad()
def mae_grados(modelo, cargador, equipo, amp):
    modelo.eval()
    suma, n = 0.0, 0
    for x, y in cargador:
        x, y = x.to(equipo, non_blocking=True), y.to(equipo, non_blocking=True)
        with torch.autocast(equipo.type, enabled=amp):
            salida = modelo(x)
        suma += (salida.float() - y).abs().sum().item() * ESCALA_ANGULO
        n += y.numel()
    return suma / n


def curvas(historial, ruta, titulo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    epocas = [h["epoca"] for h in historial]
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4))
    a.plot(epocas, [h["perdida_train"] for h in historial], color="#2E86C1")
    a.set_title("Pérdida (train)"); a.set_xlabel("época"); a.set_yscale("log"); a.grid(alpha=0.3)
    b.plot(epocas, [h["mae_train"] for h in historial], label="train", color="#2E86C1")
    b.plot(epocas, [h["mae_val"] for h in historial], label="val", color="#C0392B")
    b.set_title("MAE (°)"); b.set_xlabel("época"); b.set_yscale("log"); b.grid(alpha=0.3); b.legend()
    fig.suptitle(titulo, fontweight="bold"); fig.tight_layout()
    fig.savefig(ruta, dpi=130); plt.close(fig)


def main():

    parser = argparse.ArgumentParser(description="Entrena un modelo de alineación")
    parser.add_argument("--modelo", default="cnn", choices=list(MODELOS))
    parser.add_argument("sesion", nargs="?", help="carpeta de la sesión (por defecto, la última)")
    parser.add_argument("--epocas", type=int)
    parser.add_argument("--lote", type=int, default=128)
    parser.add_argument("--lr", type=float)
    parser.add_argument("--trabajadores", type=int, default=0,
                        help="procesos para cargar datos (0 = el principal; en Windows es lo más seguro)")
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--aumentos", choices=["gpu", "cpu"],
                        help="dónde se arman los lotes (por defecto, gpu si hay)")
    parser.add_argument("--sin-evaluar", action="store_true", help="no evaluar en test al terminar")
    args = parser.parse_args()

    epocas = args.epocas or POR_DEFECTO[args.modelo]["epocas"]
    lr = args.lr or POR_DEFECTO[args.modelo]["lr"]

    torch.manual_seed(args.semilla)
    np.random.seed(args.semilla)

    equipo = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    amp = equipo.type == "cuda"
    if amp:
        torch.backends.cudnn.benchmark = True
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("Sin GPU: se entrena en CPU (va a tardar bastante)")

    # -----------------------------
    # DATOS
    # -----------------------------

    sesion = os.path.abspath(args.sesion) if args.sesion else rutas.ultima_sesion()
    datos = cargar_recortes(sesion)

    img_train, ang_train = seleccionar(datos, "train")
    img_val, ang_val = seleccionar(datos, "val")
    print(f"Sesión {os.path.basename(sesion)} · train {len(img_train)} · val {len(img_val)} recortes")

    aumentos_gpu = (args.aumentos or ("gpu" if amp else "cpu")) == "gpu" and amp
    if aumentos_gpu:
        # Todo el dataset en la GPU y los aumentos ahí: mucho más rápido
        cargador_train = CargadorGPU(img_train, ang_train, equipo, args.lote, aumentar=True,
                                     barajar=True, descartar_ultimo=True, semilla=args.semilla)
        cargador_train_eval = CargadorGPU(img_train[::5], ang_train[::5], equipo, 512)
        cargador_val = CargadorGPU(img_val, ang_val, equipo, 512)
        print("Lotes y aumentos en la GPU")
    else:
        opciones = dict(batch_size=args.lote, num_workers=args.trabajadores,
                        pin_memory=amp, persistent_workers=args.trabajadores > 0)
        cargador_train = DataLoader(DatasetRecortes(img_train, ang_train, aumentar=True, semilla=args.semilla),
                                    shuffle=True, drop_last=True, **opciones)
        cargador_train_eval = DataLoader(DatasetRecortes(img_train[::5], ang_train[::5]), **opciones)
        cargador_val = DataLoader(DatasetRecortes(img_val, ang_val), **opciones)
        print("Lotes y aumentos en el CPU")

    # -----------------------------
    # MODELO
    # -----------------------------

    modelo = crear_modelo(args.modelo).to(equipo).to(memory_format=torch.channels_last)
    print(f"{MODELOS[args.modelo]}: {contar_parametros(modelo) / 1e6:.2f} M parámetros · "
          f"{epocas} épocas · lote {args.lote} · lr {lr}")

    optimizador = torch.optim.AdamW(modelo.parameters(), lr=lr, weight_decay=1e-4)
    planificador = torch.optim.lr_scheduler.OneCycleLR(
        optimizador, max_lr=lr, epochs=epocas, steps_per_epoch=len(cargador_train), pct_start=0.15)
    escalador = torch.amp.GradScaler(equipo.type, enabled=amp)
    perdida_fn = nn.SmoothL1Loss(beta=0.02)

    carpeta = os.path.join(rutas.ENTRENADOS, f"{args.modelo}_{os.path.basename(sesion)}")
    os.makedirs(carpeta, exist_ok=True)
    ruta_modelo = os.path.join(carpeta, "modelo.pt")

    # -----------------------------
    # ENTRENAMIENTO
    # -----------------------------

    historial = []
    mejor = float("inf")
    inicio_total = time.time()

    for epoca in range(1, epocas + 1):
        modelo.train()
        inicio = time.time()
        suma, pasos = 0.0, 0

        for x, y in cargador_train:
            x = x.to(equipo, non_blocking=True).to(memory_format=torch.channels_last)
            y = y.to(equipo, non_blocking=True)

            optimizador.zero_grad(set_to_none=True)
            with torch.autocast(equipo.type, enabled=amp):
                perdida = perdida_fn(modelo(x).float(), y)
            escalador.scale(perdida).backward()
            escalador.step(optimizador)
            escalador.update()
            planificador.step()

            suma += perdida.item()
            pasos += 1

        mae_train = mae_grados(modelo, cargador_train_eval, equipo, amp)
        mae_val = mae_grados(modelo, cargador_val, equipo, amp)
        historial.append({
            "epoca": epoca, "perdida_train": suma / pasos,
            "mae_train": mae_train, "mae_val": mae_val, "segundos": time.time() - inicio,
        })

        marca = ""
        if mae_val < mejor:
            mejor = mae_val
            marca = "  <- mejor"
            torch.save({
                "modelo": args.modelo,
                "estado": modelo.state_dict(),
                "escala_angulo": float(ESCALA_ANGULO),
                "media": MEDIA, "desviacion": DESVIACION,
                "lado_recorte": int(g.LADO_RECORTE_PX),
                "sesion": sesion,
                "epoca": epoca,
                "mae_val": float(mae_val),
            }, ruta_modelo)

        print(f"época {epoca:3d}/{epocas} · pérdida {suma / pasos:.5f} · "
              f"MAE train {mae_train:.3f}° · val {mae_val:.3f}° · {time.time() - inicio:.0f} s{marca}")

    with open(os.path.join(carpeta, "historial.csv"), "w", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(historial[0]))
        escritor.writeheader()
        escritor.writerows(historial)
    curvas(historial, os.path.join(carpeta, "curvas.png"), MODELOS[args.modelo])

    print(f"\nListo en {(time.time() - inicio_total) / 60:.1f} min · mejor MAE val {mejor:.3f}°")
    print(f"Modelo: {ruta_modelo}")

    if not args.sin_evaluar:
        from evaluar_modelo import evaluar
        evaluar(ruta_modelo, "test", sesion)


if __name__ == "__main__":
    main()
