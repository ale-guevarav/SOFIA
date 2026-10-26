"""
PUBLICAR EL MODELO - SOFIA (diagnóstico de alineación)

Copia un modelo entrenado a Alignment/pytorch/publicado/, que SÍ se sube
al repositorio (la carpeta entrenados/ no). Así el equipo lo tiene al
clonar, sin entrenar, y la app y el híbrido lo usan por defecto.

    publicado/cnn.pt          los pesos (~5 MB)
    publicado/cnn.json        de dónde salió: sesión, época, MAE en val

Uso (desde la carpeta SOFIA):
    python Alignment/pytorch/publicar_modelo.py                (la última CNN entrenada)
    python Alignment/pytorch/publicar_modelo.py <modelo.pt>

Publica solo cuando el modelo mejore: cada versión que se sube se
queda para siempre en el historial de git.
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(AQUI, "publicado")


def main():
    parser = argparse.ArgumentParser(description="Publica un modelo entrenado para el equipo")
    parser.add_argument("modelo", nargs="?", help="modelo.pt (por defecto, la última CNN)")
    args = parser.parse_args()

    if args.modelo:
        origen = os.path.abspath(args.modelo)
    else:
        candidatos = sorted(glob.glob(os.path.join(AQUI, "entrenados", "cnn_*", "modelo.pt")),
                            key=os.path.getmtime)
        if not candidatos:
            sys.exit("No hay CNN entrenadas: corre primero entrenar.py --modelo cnn")
        origen = candidatos[-1]

    import torch
    punto = torch.load(origen, map_location="cpu", weights_only=True)
    nombre = punto["modelo"]

    os.makedirs(DESTINO, exist_ok=True)
    destino = os.path.join(DESTINO, f"{nombre}.pt")
    shutil.copyfile(origen, destino)

    info = {
        "modelo": nombre,
        "sesion": os.path.basename(str(punto.get("sesion", ""))),
        "epoca": punto.get("epoca"),
        "mae_val_grados": round(float(punto.get("mae_val", float("nan"))), 4),
        "publicado": datetime.datetime.now().isoformat(timespec="seconds"),
        "origen": os.path.relpath(origen, os.path.dirname(AQUI)),
    }
    with open(os.path.join(DESTINO, f"{nombre}.json"), "w", encoding="utf-8") as archivo:
        json.dump(info, archivo, indent=2, ensure_ascii=False)

    print(f"Publicado: {destino} ({os.path.getsize(destino) / 1e6:.1f} MB)")
    print(json.dumps(info, indent=2, ensure_ascii=False))
    print("\nSúbelo con:  git add Alignment/pytorch/publicado")


if __name__ == "__main__":
    main()
