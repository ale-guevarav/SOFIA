"""
MONITOR DE MUESTREO - SOFIA (versión Python)

Hace de Monitor Serie para sofia_desalineo_azar.ino y guarda los CSV
solo, en la PC. El .ino sigue corriendo en el ESP32; este programa se
conecta a su puerto serie (CIERRA el Monitor Serie del Arduino IDE antes,
porque solo un programa puede usar el puerto).

    - Muestra todo lo que imprime el ESP32 y le manda las teclas que
      picas (d, D, 0, r, f, x, n) sin tener que dar Enter.
    - AUTOGUARDADO: cada vez que el ESP32 guarda / borra una muestra, la
      copia de la PC se actualiza en muestreos/autoguardado_<fecha>.csv.
      Si el ESP32 se reinicia o se desconecta, lo de la PC no se pierde.
    - Al picar f: lo que imprime el ESP32 entre "----- CSV" y "----- FIN"
      se guarda en muestreos/muestreo_<fecha_hora>.csv.
    - q (o Esc): salir. Si hubo cambios desde la última f, antes de salir
      pide el CSV al ESP32 y lo guarda.
    - Todo lo que llega se guarda también en muestreos/registro_<fecha>.txt

Necesita pyserial:   pip install pyserial

Usar:
    python monitor_muestreo.py COM5
    python monitor_muestreo.py /dev/ttyACM0          (Linux)
    python monitor_muestreo.py COM5 otra_carpeta     (carpeta de salida)
    python monitor_muestreo.py --puertos             (lista los puertos)
"""

import os
import re
import sys
import time
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("Falta pyserial: pip install pyserial")


NUM_UNIDADES = 16
BAUD = 115200
ENCABEZADO = "muestra,foto,tipo,numero,theta1_deg,theta2_deg"


# =============================================
# TECLADO (sin Enter)
# =============================================

if os.name == "nt":
    import msvcrt

    class Teclado:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def tecla(self):
            """La tecla picada, o None."""
            if not msvcrt.kbhit():
                return None
            c = msvcrt.getwch()
            if c in ("\x00", "\xe0"):      # flechas, F1...: se ignoran
                msvcrt.getwch()
                return None
            return c
else:
    import select
    import termios
    import tty

    class Teclado:
        def __enter__(self):
            self._fd = sys.stdin.fileno()
            self._original = None
            if os.isatty(self._fd):
                self._original = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
            return self

        def __exit__(self, *_):
            if self._original is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original)

        def tecla(self):
            if select.select([sys.stdin], [], [], 0)[0]:
                c = sys.stdin.read(1)
                return c or None
            return None


# =============================================
# MUESTREO (copia en la PC)
# =============================================

class Muestreo:

    def __init__(self, carpeta):
        self.carpeta = carpeta
        os.makedirs(carpeta, exist_ok=True)
        self.sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.registro = open(os.path.join(carpeta, f"registro_{self.sello}.txt"), "a", encoding="utf-8")
        self.muestras = {}          # numero -> {"tipo", "x": [16], "y": [16]}
        self.ultima = None
        self.ultimo_tipo = "?"
        self.cambios = False
        self.en_csv = False
        self.bloque = []

    def tecla_enviada(self, c):
        if c in ("d", "D", "0"):
            self.ultimo_tipo = c

    def hay_cambios(self):
        return self.cambios and bool(self.muestras)

    def linea(self, l):
        """Procesa una línea completa del ESP32."""
        self.registro.write(l + "\n")
        self.registro.flush()

        if self.en_csv:
            if l.startswith("----- FIN"):
                self._guardar_bloque()
                self.en_csv = False
            elif l:
                self.bloque.append(l)
            return
        if l.startswith("----- CSV"):
            self.en_csv = True
            self.bloque = []
            return

        m = re.match(r"\[MUESTREO\] Muestra (\d+) guardada", l)
        if m:
            n = int(m.group(1))
            self.muestras[n] = {"tipo": self.ultimo_tipo, "x": [0.0] * NUM_UNIDADES, "y": [0.0] * NUM_UNIDADES}
            self.ultima = n
            self.cambios = True
            self._autoguardar()
            return

        m = re.match(r"\[MUESTREO\] Borrada la muestra (\d+)", l)
        if m:
            self.muestras.pop(int(m.group(1)), None)
            self.cambios = True
            self._autoguardar()
            return

        if l.startswith("[MUESTREO] Muestreo nuevo"):
            self.muestras.clear()
            self.cambios = True
            self._autoguardar()
            return

        if l.startswith("[DESALINEO] CSV ") and self.ultima in self.muestras:
            # "u,x,y;u,x,y;..." de la última muestra (d / D)
            muestra = self.muestras[self.ultima]
            for trozo in l[len("[DESALINEO] CSV "):].split(";"):
                try:
                    u, x, y = trozo.split(",")
                    u = int(u)
                    if 0 <= u < NUM_UNIDADES:
                        muestra["x"][u] = float(x)
                        muestra["y"][u] = float(y)
                except ValueError:
                    pass
            self._autoguardar()

    def _autoguardar(self):
        ruta = os.path.join(self.carpeta, f"autoguardado_{self.sello}.csv")
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(ENCABEZADO + "\n")
            for n in sorted(self.muestras):
                m = self.muestras[n]
                for u in range(NUM_UNIDADES):
                    f.write(f"{n},{n + 1},{m['tipo']},{u},{m['x'][u]:.1f},{m['y'][u]:.1f}\n")

    def _guardar_bloque(self):
        if not self.bloque:
            return
        ruta = os.path.join(self.carpeta, f"muestreo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(self.bloque) + "\n")
        self.cambios = False
        print(f"\n>>> CSV guardado: {os.path.abspath(ruta)}  "
              f"({(len(self.bloque) - 1) // NUM_UNIDADES} muestras)", flush=True)


# =============================================
# MAIN
# =============================================

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 1
    if sys.argv[1] == "--puertos":
        for p in list_ports.comports():
            print(f"{p.device:12s} {p.description}")
        return 0

    nombre = sys.argv[1]
    carpeta = sys.argv[2] if len(sys.argv) >= 3 else "muestreos"

    try:
        puerto = serial.Serial(nombre, BAUD, timeout=0)
    except serial.SerialException as error:
        print(f"No se pudo abrir {nombre}: {error}\n"
              "(¿es el puerto correcto? ¿está abierto el Monitor Serie del Arduino IDE?)")
        print("Puertos disponibles:")
        for p in list_ports.comports():
            print(f"  {p.device:12s} {p.description}")
        return 1

    muestreo = Muestreo(carpeta)
    print(f"=== Monitor de muestreo SOFIA en {nombre} ===\n"
          "Teclas al ESP32: d D 0 r f x n   |   q o Esc: salir (guarda el CSV si falta)\n"
          f"Archivos en: {os.path.abspath(carpeta)}\n", flush=True)

    pendiente = ""
    salir = False
    fin_espera = None

    with Teclado() as teclado:
        try:
            while True:
                # 1. Lo que manda el ESP32
                try:
                    datos = puerto.read(512)
                except serial.SerialException:
                    print(f"\n>>> Se perdió el puerto (¿se desconectó el ESP32?). "
                          f"Lo guardado está en {os.path.abspath(carpeta)}")
                    return 2
                if datos:
                    texto = datos.decode("utf-8", errors="replace")
                    print(texto, end="", flush=True)
                    pendiente += texto
                    while "\n" in pendiente:
                        l, pendiente = pendiente.split("\n", 1)
                        muestreo.linea(l.rstrip("\r"))

                # 2. Teclas
                c = teclado.tecla()
                if c is not None and not salir:
                    if c in ("q", "Q", "\x1b"):
                        if muestreo.hay_cambios():
                            print("\n>>> Pidiendo el CSV al ESP32 antes de salir...", flush=True)
                            puerto.write(b"f")
                            salir = True
                            fin_espera = time.monotonic() + 5
                        else:
                            break
                    elif c not in ("\r", "\n"):
                        puerto.write(c.encode("utf-8"))
                        muestreo.tecla_enviada(c)

                # 3. Salida: cuando llegó el CSV completo (o se acabó la espera)
                if salir and not muestreo.en_csv and not muestreo.hay_cambios():
                    break
                if salir and time.monotonic() > fin_espera:
                    print(f"\n>>> No llegó el CSV; queda el autoguardado en {os.path.abspath(carpeta)}")
                    break

                time.sleep(0.005)
        except KeyboardInterrupt:
            print(f"\n>>> Ctrl+C: queda el autoguardado en {os.path.abspath(carpeta)}")
        finally:
            puerto.close()

    print(f"\nListo. Muestras en la PC: {len(muestreo.muestras)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
