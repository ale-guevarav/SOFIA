"""
ENTRENAR - SOFIA (diagnóstico de alineación)

Entrena la CNN pequeña (o la ResNet18) con los recortes de una sesión y al
final la evalúa en test (igual que el método geométrico).

    - Optimizador AdamW con OneCycle (sube y baja el learning rate).
    - Precisión mixta (AMP) en la GPU: más rápido y usa menos memoria.
    - Pérdida SmoothL1 sobre ángulo / 30°.
    - Cada época se mide el MAE en val (grados) y se guarda el MEJOR.

Sale en Alignment/build/entrenados/<nombre>/   (nombre = <modelo>_<sesión>):
    modelo.pt       pesos de la MEJOR época (lo que usa la app / inferencia.py)
    ultimo.pt       estado completo de la última época terminada (para reanudar)
    historial.csv   pérdida y MAE por época
    curvas.png      gráfica del historial

ENTRENAR POR PARTES (por ejemplo, un rato cada día)
---------------------------------------------------
Al terminar cada época se guarda ultimo.pt. Se puede parar cuando sea:

    --minutos 60          para solo después de la época en la que pasen 60 min
    Ctrl+C                para ya; se pierde solo la época que iba a la mitad

y seguir otro día exactamente donde se quedó (mismo learning rate, misma
época, mismo mejor modelo):

    python Alignment/build/entrenar.py --reanudar                 (el último sin terminar)
    python Alignment/build/entrenar.py --reanudar <carpeta>       (uno en particular)
    python Alignment/build/entrenar.py --reanudar --minutos 60    (otra hora y para)

AFINAR UN MODELO YA ENTRENADO (más épocas, o fotos reales)
----------------------------------------------------------
    --desde <modelo.pt>   empieza con esos pesos en lugar de desde cero,
                          con un learning rate 10 veces menor y 10 épocas
                          (se cambian con --lr y --epocas)

    python Alignment/build/entrenar.py --desde Alignment/results/modelo/cnn.pt
    python Alignment/build/entrenar.py --desde <modelo.pt> <sesión de fotos reales> --epocas 15

Sale en entrenados/<modelo>_<sesión>_afinado/ (o --nombre).

Uso normal (desde la carpeta SOFIA):
    python Alignment/build/entrenar.py --modelo cnn
    python Alignment/build/entrenar.py --modelo cnn --epocas 40 --minutos 90
"""

import argparse
import csv
import glob
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
AFINAR = {"epocas": 10, "divisor_lr": 10}     # --desde: menos épocas y learning rate más bajo

ULTIMO = "ultimo.pt"
CADA_SEGUNDOS = 2.0                           # cada cuánto se actualiza el avance dentro de la época


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


def guardar_historial(historial, carpeta, titulo):
    if not historial:
        return
    with open(os.path.join(carpeta, "historial.csv"), "w", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(historial[0]))
        escritor.writeheader()
        escritor.writerows(historial)
    curvas(historial, os.path.join(carpeta, "curvas.png"), titulo)


def buscar_sin_terminar():
    """Carpeta del entrenamiento más reciente que no ha terminado."""
    candidatos = []
    for ruta in glob.glob(os.path.join(rutas.ENTRENADOS, "*", ULTIMO)):
        try:
            punto = torch.load(ruta, map_location="cpu", weights_only=False)
        except Exception:
            continue
        if not punto.get("terminado"):
            candidatos.append((os.path.getmtime(ruta), os.path.dirname(ruta)))
    if not candidatos:
        sys.exit("No hay entrenamientos sin terminar en " + rutas.ENTRENADOS)
    return max(candidatos)[1]


def leer_argumentos():
    parser = argparse.ArgumentParser(description="Entrena un modelo de alineación")
    parser.add_argument("--modelo", default="cnn", choices=list(MODELOS))
    parser.add_argument("sesion", nargs="?", help="carpeta de la sesión (por defecto, la última)")
    parser.add_argument("--epocas", type=int, help="épocas en total")
    parser.add_argument("--lote", type=int, default=128)
    parser.add_argument("--lr", type=float)
    parser.add_argument("--trabajadores", type=int, default=0,
                        help="procesos para cargar datos en CPU (0 = el principal; en Windows es lo más seguro)")
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--aumentos", choices=["gpu", "cpu"],
                        help="dónde se arman los lotes (por defecto, gpu si hay)")
    parser.add_argument("--desde", help="modelo.pt con el que se empieza (afinar)")
    parser.add_argument("--nombre", help="nombre de la carpeta en entrenados/")
    parser.add_argument("--minutos", type=float, help="parar después de la época en la que pasen estos minutos")
    parser.add_argument("--reanudar", nargs="?", const="", metavar="CARPETA",
                        help="seguir un entrenamiento pausado (sin carpeta: el último sin terminar)")
    parser.add_argument("--sin-evaluar", action="store_true", help="no evaluar en test al terminar")
    return parser.parse_args()


def main():

    args = leer_argumentos()

    equipo = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    amp = equipo.type == "cuda"
    if amp:
        torch.backends.cudnn.benchmark = True
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("Sin GPU: se entrena en CPU (va a tardar bastante)")

    # -----------------------------
    # CONFIGURACIÓN (nueva o la del entrenamiento pausado)
    # -----------------------------

    punto = None
    if args.reanudar is not None:
        carpeta = os.path.abspath(args.reanudar) if args.reanudar else buscar_sin_terminar()
        ruta_ultimo = os.path.join(carpeta, ULTIMO)
        if not os.path.isfile(ruta_ultimo):
            sys.exit(f"No hay {ULTIMO} en {carpeta}")
        # Archivo propio (lo escribe este script): incluye optimizador y planificador
        punto = torch.load(ruta_ultimo, map_location="cpu", weights_only=False)
        if punto.get("terminado"):
            sys.exit(f"Ese entrenamiento ya terminó ({punto['epoca']} épocas). "
                     "Para entrenarlo más usa --desde con su modelo.pt")
        config = punto["config"]
        config["sesion"] = rutas.resolver_sesion(config["sesion"])
        print(f"Reanudando {os.path.basename(carpeta)} desde la época {punto['epoca'] + 1}/{config['epocas']}")
    else:
        sesion = os.path.abspath(args.sesion) if args.sesion else rutas.ultima_sesion()
        nombre_modelo = args.modelo
        punto_desde = None
        if args.desde:
            punto_desde = torch.load(args.desde, map_location="cpu", weights_only=True)
            nombre_modelo = punto_desde["modelo"]
            lado_m = punto_desde.get("lado_recorte_m")
            if lado_m is not None and abs(lado_m - g.LADO_RECORTE_M) > 1e-6:
                print(f"⚠ El modelo se entrenó con recortes de {lado_m * 1000:.0f} mm y ahora son de "
                      f"{g.LADO_RECORTE_M * 1000:.0f} mm (cambió geometria.py): afinar puede no bastar")
        base = POR_DEFECTO[nombre_modelo]
        config = {
            "modelo": nombre_modelo,
            "sesion": sesion,
            "epocas": args.epocas or (AFINAR["epocas"] if args.desde else base["epocas"]),
            "lote": args.lote,
            "lr": args.lr or (base["lr"] / AFINAR["divisor_lr"] if args.desde else base["lr"]),
            "semilla": args.semilla,
            "aumentos": args.aumentos,
            "desde": os.path.abspath(args.desde) if args.desde else None,
        }
        nombre = args.nombre or (f"{nombre_modelo}_{os.path.basename(sesion)}"
                                 + ("_afinado" if args.desde else ""))
        carpeta = os.path.join(rutas.ENTRENADOS, nombre)
        ruta_ultimo = os.path.join(carpeta, ULTIMO)

        if os.path.isfile(ruta_ultimo):
            previo = torch.load(ruta_ultimo, map_location="cpu", weights_only=False)
            if not previo.get("terminado"):
                sys.exit(f"{nombre} tiene un entrenamiento pausado en la época {previo['epoca']}.\n"
                         f"  Para seguirlo:        python Alignment/build/entrenar.py --reanudar\n"
                         f"  Para empezar de nuevo: borra {ruta_ultimo}")

    os.makedirs(carpeta, exist_ok=True)
    ruta_modelo = os.path.join(carpeta, "modelo.pt")
    sesion, epocas, lr = config["sesion"], config["epocas"], config["lr"]
    titulo = MODELOS[config["modelo"]]

    torch.manual_seed(config["semilla"])
    np.random.seed(config["semilla"])

    # -----------------------------
    # DATOS
    # -----------------------------

    datos = cargar_recortes(sesion)

    img_train, ang_train = seleccionar(datos, "train")
    img_val, ang_val = seleccionar(datos, "val")
    print(f"Sesión {os.path.basename(sesion)} · train {len(img_train)} · val {len(img_val)} recortes")

    aumentos_gpu = (config["aumentos"] or ("gpu" if amp else "cpu")) == "gpu" and amp
    if aumentos_gpu:
        # Todo el dataset en la GPU y los aumentos ahí: mucho más rápido
        cargador_train = CargadorGPU(img_train, ang_train, equipo, config["lote"], aumentar=True,
                                     barajar=True, descartar_ultimo=True, semilla=config["semilla"])
        cargador_train_eval = CargadorGPU(img_train[::5], ang_train[::5], equipo, 512)
        cargador_val = CargadorGPU(img_val, ang_val, equipo, 512)
        print("Lotes y aumentos en la GPU")
    else:
        opciones = dict(batch_size=config["lote"], num_workers=args.trabajadores,
                        pin_memory=amp, persistent_workers=args.trabajadores > 0)
        dataset_train = DatasetRecortes(img_train, ang_train, aumentar=True, semilla=config["semilla"])
        cargador_train = DataLoader(dataset_train, shuffle=True, drop_last=True, **opciones)
        cargador_train_eval = DataLoader(DatasetRecortes(img_train[::5], ang_train[::5]), **opciones)
        cargador_val = DataLoader(DatasetRecortes(img_val, ang_val), **opciones)
        print("Lotes y aumentos en el CPU")

    # -----------------------------
    # MODELO
    # -----------------------------

    # Con pesos de otro modelo (o del pausado) no hace falta bajar los de ImageNet
    modelo = crear_modelo(config["modelo"], preentrenada=not (config["desde"] or punto))
    if punto is None and config["desde"]:
        modelo.load_state_dict(punto_desde["estado"])
        print(f"Empieza con los pesos de {config['desde']}")
    modelo = modelo.to(equipo).to(memory_format=torch.channels_last)

    optimizador = torch.optim.AdamW(modelo.parameters(), lr=lr, weight_decay=1e-4)
    planificador = torch.optim.lr_scheduler.OneCycleLR(
        optimizador, max_lr=lr, epochs=epocas, steps_per_epoch=len(cargador_train), pct_start=0.15)
    escalador = torch.amp.GradScaler(equipo.type, enabled=amp)
    perdida_fn = nn.SmoothL1Loss(beta=0.02)

    historial = []
    mejor = float("inf")
    primera = 1

    if punto is not None:
        modelo.load_state_dict(punto["estado"])
        optimizador.load_state_dict(punto["optimizador"])
        planificador.load_state_dict(punto["planificador"])
        escalador.load_state_dict(punto["escalador"])
        historial = punto["historial"]
        mejor = punto["mejor"]
        primera = punto["epoca"] + 1
        torch.set_rng_state(punto["rng"]["torch"])
        np.random.set_state(punto["rng"]["numpy"])
        if amp and punto["rng"].get("cuda") is not None:
            torch.cuda.set_rng_state_all(punto["rng"]["cuda"])
        if aumentos_gpu and punto["rng"].get("cargador") is not None:
            cargador_train.generador.set_state(punto["rng"]["cargador"])
        elif not aumentos_gpu and punto["rng"].get("dataset") is not None:
            dataset_train.rng.bit_generator.state = punto["rng"]["dataset"]

    print(f"{titulo}: {contar_parametros(modelo) / 1e6:.2f} M parámetros · "
          f"{epocas} épocas · lote {config['lote']} · lr {lr}"
          + (f" · para a los {args.minutos:g} min" if args.minutos else ""))

    def guardar_estado(epoca, terminado=False):
        estado_rng = {
            "torch": torch.get_rng_state(),
            "numpy": np.random.get_state(),
            "cuda": torch.cuda.get_rng_state_all() if amp else None,
            "cargador": cargador_train.generador.get_state() if aumentos_gpu else None,
            "dataset": None if aumentos_gpu else dataset_train.rng.bit_generator.state,
        }
        temporal = ruta_ultimo + ".tmp"
        torch.save({
            "config": config, "epoca": epoca, "terminado": terminado,
            "estado": modelo.state_dict(), "optimizador": optimizador.state_dict(),
            "planificador": planificador.state_dict(), "escalador": escalador.state_dict(),
            "historial": historial, "mejor": mejor, "rng": estado_rng,
        }, temporal)
        os.replace(temporal, ruta_ultimo)      # así nunca queda un ultimo.pt a medias

    # -----------------------------
    # ENTRENAMIENTO
    # -----------------------------

    inicio_sesion = time.time()
    epoca = primera - 1

    try:
        for epoca in range(primera, epocas + 1):
            modelo.train()
            inicio = time.time()
            suma, pasos = 0.0, 0
            total_lotes = len(cargador_train)
            ultimo_aviso = inicio

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

                # Avance dentro de la época (se reescribe la misma línea)
                ahora = time.time()
                if ahora - ultimo_aviso >= CADA_SEGUNDOS:
                    ultimo_aviso = ahora
                    porcentaje = 100 * pasos / total_lotes
                    resta = (ahora - inicio) / pasos * (total_lotes - pasos)
                    print(f"  época {epoca}/{epocas} · lote {pasos}/{total_lotes} ({porcentaje:.0f} %) · "
                          f"pérdida {suma / pasos:.5f} · termina en ~{resta / 60:.1f} min   ",
                          end="\r", flush=True)

            print(f"  época {epoca}/{epocas} · evaluando en train y val...{' ' * 40}", end="\r", flush=True)

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
                    "modelo": config["modelo"],
                    "estado": modelo.state_dict(),
                    "escala_angulo": float(ESCALA_ANGULO),
                    "media": MEDIA, "desviacion": DESVIACION,
                    "lado_recorte": int(g.LADO_RECORTE_PX),
                    "lado_recorte_m": float(g.LADO_RECORTE_M),
                    "sesion": sesion,
                    "epoca": epoca,
                    "mae_val": float(mae_val),
                    "desde": os.path.basename(config["desde"]) if config["desde"] else None,
                }, ruta_modelo)

            guardar_estado(epoca, terminado=epoca == epocas)

            transcurrido = time.time() - inicio_sesion
            faltan = (epocas - epoca) * transcurrido / (epoca - primera + 1)
            print(" " * 100, end="\r")      # borra la línea de avance
            print(f"época {epoca:3d}/{epocas} · pérdida {suma / pasos:.5f} · "
                  f"MAE train {mae_train:.3f}° · val {mae_val:.3f}° · {time.time() - inicio:.0f} s"
                  f" · faltan ~{faltan / 60:.0f} min{marca}")

            if args.minutos and epoca < epocas and transcurrido >= args.minutos * 60:
                print(f"\nPausa: pasaron {transcurrido / 60:.0f} min (--minutos {args.minutos:g}).")
                break

    except KeyboardInterrupt:
        print(" " * 100, end="\r")
        print(f"\nPausa con Ctrl+C: se pierde solo la época {epoca} (iba a la mitad).")
        epoca -= 1

    guardar_historial(historial, carpeta, titulo)

    if not historial or historial[-1]["epoca"] < epocas:
        hechas = historial[-1]["epoca"] if historial else 0
        print(f"Guardado hasta la época {hechas}/{epocas} en {ruta_ultimo}")
        print("Para seguir:  python Alignment/build/entrenar.py --reanudar")
        return

    print(f"\nListo · mejor MAE val {mejor:.3f}°")
    print(f"Modelo: {ruta_modelo}")

    if not args.sin_evaluar:
        from evaluar_modelo import evaluar
        evaluar(ruta_modelo, "test", sesion)


if __name__ == "__main__":
    main()
