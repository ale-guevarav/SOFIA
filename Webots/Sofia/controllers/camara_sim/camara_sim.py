"""
CÁMARA CENITAL DE LA SIMULACIÓN - SOFIA (Webots)

Nodo propio (Robot "camara_cenital" con una Camera) que SOLO manda
imágenes a la GUI por un canal aparte del de comandos:

    este controlador --TCP :5556--> GUI (interfaz/sim_camera.py)

No recibe nada ni toca a los paneles: si se apaga, la simulación
y el enlace de comandos siguen igual.

Cada imagen:  "SOFC" | ancho u16 | alto u16 | tamaño u32 | BGRA
"""

import socket
import struct

from controller import Robot


HOST = "127.0.0.1"
PORT = 5556

# Cada cuánto se toma una imagen (ms). Debe ser múltiplo del
# basicTimeStep del mundo (8 ms): 64 ms ~ 15 FPS
PERIODO_MS = 64

HEADER = struct.Struct("<4sHHI")


def main():

    robot = Robot()
    time_step = int(robot.getBasicTimeStep())

    camera = robot.getDevice("camara")
    camera.enable(PERIODO_MS)

    width = camera.getWidth()
    height = camera.getHeight()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    server.setblocking(False)

    client = None
    elapsed_ms = 0

    print(f"[CAMARA] {width}x{height} en {HOST}:{PORT}")

    while robot.step(time_step) != -1:

        # -----------------------------
        # ACEPTAR A LA GUI
        # -----------------------------

        if client is None:
            try:
                client, _ = server.accept()
                # Bloqueante con límite: si la GUI no lee, se suelta
                client.settimeout(0.5)
                print("[CAMARA] GUI conectada")
            except BlockingIOError:
                pass

        # -----------------------------
        # ENVIAR UNA IMAGEN CADA PERIODO
        # -----------------------------

        elapsed_ms += time_step

        if client is None or elapsed_ms < PERIODO_MS:
            continue

        elapsed_ms = 0

        image = camera.getImage()   # BGRA, ancho * alto * 4 bytes

        if not image:
            continue

        try:
            client.sendall(HEADER.pack(b"SOFC", width, height, len(image)) + image)
        except OSError:
            print("[CAMARA] GUI desconectada")
            client.close()
            client = None

    if client is not None:
        client.close()
    server.close()


if __name__ == "__main__":
    main()
