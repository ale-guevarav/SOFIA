"""
PRUEBA AUTOMÁTICA DE COMUNICACIÓN Y ESTRÉS EN SIMULACIÓN - SOFIA

Prueba el enlace de la GUI contra el controlador de la simulación sin
abrir Webots y sin ESP32. Se corre desde la carpeta Vision:

    python -m evaluacion.prueba_comunicacion_sim

Tarda unos 5 minutos y guarda todo en metrics/prueba_sim/:
    resultados.json, salida_prueba.txt y una sesión del registro de la
    GUI (comandos.csv, eventos.csv, bitacora.txt, resumen.md).

Qué se usa (todo es el código real del proyecto):
    PC        WebotsLink de la GUI (comunicacion/sim_link.py) con su
              emulador de canal BLE cuando la prueba lo pide.
    Robot     el controlador de la simulación
              (Webots/Sofia/controllers/sofia_maestro_sim), con un
              Supervisor mínimo en lugar de Webots. Aplica las mismas
              reglas que el firmware: ACK/NACK, duplicados, estado seguro.
    Registro  SessionLogger de la GUI.

Escenarios:
    S1  Ciclo de las 5 posturas, 20 veces cada una, canal limpio
    S2  300 posturas con el canal BLE simulado (3 % pérdidas, 2 % dañadas)
    S3  Cambios rápidos: una postura nueva cada 100 ms durante 30 s
    S4  TRACKING a 20 Hz + una postura cada 2 s durante 60 s
    S5  Simulación detenida 5 s y reanudada (como apagar el ESP32), 5 veces
    S6  Robot sin responder 6 s con la conexión abierta, 5 veces
    S7  Reglas del robot: duplicados, CRC dañado y estado seguro a 3 s

No usa la cámara: las posturas se mandan como lo hace la GUI al detectarlas.
"""

import importlib.util
import json
import math
import os
import random
import socket
import struct
import sys
import threading
import time
import types
from types import SimpleNamespace

VISION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(VISION)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VISION, "metrics", "prueba_sim")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, VISION)

from PySide6.QtCore import QCoreApplication           # noqa: E402

from comunicacion import protocol as p                # noqa: E402
from comunicacion.sim_link import WebotsLink          # noqa: E402
from evaluacion.session_logger import SessionLogger   # noqa: E402

PORT = 5655
T0 = time.monotonic()
LOG = open(os.path.join(OUT, "salida_prueba.txt"), "w", encoding="utf-8")


def log(*args):
    line = f"{time.monotonic() - T0:7.2f}  " + " ".join(str(a) for a in args)
    LOG.write(line + "\n")
    LOG.flush()


# =============================================
# WEBOTS MÍNIMO PARA EL CONTROLADOR REAL
# =============================================

class FakeField:
    def setSFVec3f(self, value):
        pass


class FakeNode:
    def getField(self, name):
        return FakeField()


class FakeSupervisor:
    def __init__(self):
        self.stopped = False
        self.custom = []

    def getBasicTimeStep(self):
        return 16

    def step(self, ms):
        time.sleep(ms / 1000)
        return -1 if self.stopped else 0

    def getFromDef(self, name):
        return FakeNode()

    def getSelf(self):
        return FakeNode()

    def setCustomData(self, text):
        self.custom.append((time.monotonic(), text))

    def getTime(self):
        return time.monotonic() - T0


sys.modules["controller"] = types.SimpleNamespace(Supervisor=FakeSupervisor)
os.environ["SOFIA_PROTOCOL"] = os.path.join(VISION, "comunicacion", "protocol.py")

_spec = importlib.util.spec_from_file_location(
    "maestro_sim",
    os.path.join(REPO, "Webots", "Sofia", "controllers", "sofia_maestro_sim", "sofia_maestro_sim.py"),
)
maestro_mod = importlib.util.module_from_spec(_spec)
_real_print = print
maestro_mod.print = lambda *a, **k: log("[MAESTRO]", *a)
_spec.loader.exec_module(maestro_mod)
maestro_mod.PORT = PORT


class MaestroRunner:
    """Arranca, detiene y congela el maestro de la simulación."""

    def __init__(self):
        self.m = None
        self.thread = None
        self.frozen = False
        self.executions = []      # (t, pose_id)
        self.safe_events = []     # (t, motivo)

    def start(self):
        self.m = maestro_mod.Maestro()
        m = self.m
        real_receive = m.receive
        m.receive = lambda: None if self.frozen else real_receive()
        real_on_pose = m.on_pose
        m.on_pose = lambda pid: (self.executions.append((time.monotonic(), pid)), real_on_pose(pid))
        real_safe = m.enter_safe_state

        def safe(reason):
            if not m.safe:
                self.safe_events.append((time.monotonic(), reason))
            real_safe(reason)

        m.enter_safe_state = safe
        self.thread = threading.Thread(target=m.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.m.robot.stopped = True
        self.thread.join(timeout=3)


maestro = MaestroRunner()

# =============================================
# PC: ENLACE REAL DE LA GUI + REGISTRO REAL
# =============================================

app = QCoreApplication([])
link = WebotsLink(port=PORT)
session = SessionLogger(base_dir=OUT)

events = []          # (t, tipo, detalle)
done = []            # dicts de command_done
done_event = threading.Event()

link.log.connect(lambda s: (log("[PC]", s), session.log_line(f"[Webots] {s}")))


def on_done(info):
    info = dict(info)
    info["t"] = time.monotonic()
    done.append(info)
    session.command("Webots", info)
    done_event.set()


def on_event(kind, detail):
    events.append((time.monotonic(), kind, detail))
    session.event("Webots", kind, detail)


link.command_done.connect(on_done)
link.link_event.connect(on_event)

results = {}


def wait_until(cond, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def label(name):
    session.set_label(name)
    log("=====", name)


def pose_tag(pose):
    return {"postura": p.POSE_NAMES[pose], "proc_ms": 0.0}


def send_and_wait(pose, timeout=3.0):
    done_event.clear()
    n = len(done)
    link.send_pose(pose, pose_tag(pose))
    wait_until(lambda: len(done) > n, timeout)
    return done[-1] if len(done) > n else None


def pose_stats(rows):
    ok = [r for r in rows if r["ok"]]
    lat = sorted(r["cola_ms"] for r in ok)
    att = [r["intentos"] for r in rows]
    pct = lambda q: lat[min(len(lat) - 1, round(q / 100 * (len(lat) - 1)))] if lat else None
    return {
        "enviados": len(rows),
        "ack": len(ok),
        "exito_pct": round(100 * len(ok) / len(rows), 2) if rows else None,
        "intentos_prom": round(sum(att) / len(att), 3) if att else None,
        "con_reintento": sum(1 for a in att if a > 1),
        "lat_prom_ms": round(sum(lat) / len(lat), 1) if lat else None,
        "lat_p95_ms": round(pct(95), 1) if lat else None,
        "lat_max_ms": round(lat[-1], 1) if lat else None,
        "fallas": {d: sum(1 for r in rows if not r["ok"] and r["detalle"] == d)
                   for d in {r["detalle"] for r in rows if not r["ok"]}},
    }


def raw_client():
    s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.settimeout(0.5)
    return s


def raw_send(s, frame):
    s.sendall(struct.pack("B", len(frame)) + frame)


def raw_recv(s):
    out = []
    buf = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    while buf and len(buf) >= 1 + buf[0]:
        n = buf[0]
        out.append(p.parse_frame(buf[1:1 + n]))
        buf = buf[1 + n:]
    return out


# =============================================
# ESCENARIOS
# =============================================

def scenario():

    try:
        maestro.start()
        time.sleep(0.3)
        link.connect_device()
        assert wait_until(lambda: link.connected, 5), "no conectó"

        # ---------------------------------------------------------
        # S1. Ciclo de las 5 posturas, canal limpio, 20 repeticiones
        # ---------------------------------------------------------
        label("S1 ciclo 5 posturas")
        start = len(done)
        exec_start = len(maestro.executions)
        for _ in range(20):
            for pose in range(1, 6):
                send_and_wait(pose)
                time.sleep(0.05)
        rows = done[start:]
        execs = maestro.executions[exec_start:]
        per_pose = {}
        for pose in range(1, 6):
            name = p.POSE_NAMES[pose]
            pr = [r for r in rows if r["tag"]["postura"] == name]
            per_pose[name] = {
                "enviados": len(pr),
                "ack": sum(r["ok"] for r in pr),
                "ejecutadas": sum(1 for _, pid in execs if pid == pose),
                "lat_prom_ms": round(sum(r["cola_ms"] for r in pr if r["ok"]) / max(1, sum(r["ok"] for r in pr)), 2),
            }
        results["S1"] = {"total": pose_stats(rows), "por_postura": per_pose}

        # ---------------------------------------------------------
        # S2. Canal BLE simulado: 300 posturas una por una
        # ---------------------------------------------------------
        label("S2 canal BLE simulado")
        random.seed(7)
        link.channel_emulation = True
        nacks0 = link.stats["nacks"]
        start = len(done)
        exec_start = len(maestro.executions)
        for i in range(300):
            send_and_wait(1 + i % 5, timeout=5)
            time.sleep(0.1)
        rows = done[start:]
        results["S2"] = pose_stats(rows)
        results["S2"]["nacks"] = link.stats["nacks"] - nacks0
        results["S2"]["ejecutadas_maestro"] = len(maestro.executions) - exec_start
        results["S2"]["caidas"] = sum(1 for _, k, _ in events if k == "perdido")

        # ---------------------------------------------------------
        # S3. Cambios rápidos: una postura nueva cada 100 ms, 30 s,
        #     canal simulado, sin esperar el ACK
        # ---------------------------------------------------------
        label("S3 cambios rapidos")
        start = len(done)
        exec_start = len(maestro.executions)
        ev_start = len(events)
        sent = 0
        t_end = time.monotonic() + 30
        last = 0
        while time.monotonic() < t_end:
            pose = 1 + (last % 5)
            last += 1
            link.send_pose(pose, pose_tag(pose))
            sent += 1
            time.sleep(0.1)
        wait_until(lambda: len(done) - start >= sent, 30)
        rows = done[start:]
        results["S3"] = pose_stats(rows)
        results["S3"]["pedidos"] = sent
        results["S3"]["ejecutadas_maestro"] = len(maestro.executions) - exec_start
        results["S3"]["caidas"] = sum(1 for _, k, _ in events[ev_start:] if k == "perdido")

        # ---------------------------------------------------------
        # S4. TRACK a 20 Hz + una postura cada 2 s durante 60 s,
        #     canal simulado (modo TRACKING)
        # ---------------------------------------------------------
        label("S4 tracking 20 Hz + posturas")
        link.send_mode("TRACKING")
        time.sleep(0.5)
        start = len(done)
        ev_start = len(events)
        track0 = link.stats["tramas_track"]
        lat0 = link.stats["latidos"]
        t_end = time.monotonic() + 60
        next_pose = time.monotonic() + 2
        k = 0
        while time.monotonic() < t_end:
            a = (k % 360)
            hand = SimpleNamespace(label="DERECHA", x_norm=0.5 * math.cos(math.radians(a)),
                                   y_norm=0.5 * math.sin(math.radians(a)),
                                   magnitude_norm=0.5, angle=float(a))
            link.send_track(hand)
            k += 3
            if time.monotonic() >= next_pose:
                pose = 1 + (k // 3) % 5
                link.send_pose(pose, pose_tag(pose))
                next_pose += 2
            time.sleep(1 / 30)
        time.sleep(2)
        rows = [r for r in done[start:] if r["comando"] == "POSE"]
        results["S4"] = pose_stats(rows)
        results["S4"]["tramas_track"] = link.stats["tramas_track"] - track0
        results["S4"]["latidos"] = link.stats["latidos"] - lat0
        results["S4"]["caidas"] = sum(1 for _, k2, _ in events[ev_start:] if k2 == "perdido")
        link.send_mode("JUEGO")
        time.sleep(0.5)

        # ---------------------------------------------------------
        # S5. Simulación detenida 5 s y reanudada, 5 veces
        #     (equivale a apagar/resetear el ESP32)
        # ---------------------------------------------------------
        label("S5 simulacion detenida")
        link.channel_emulation = False
        recov = []
        for i in range(5):
            ev_start = len(events)
            t_stop = time.monotonic()
            maestro.stop()
            time.sleep(5)
            maestro.start()
            ok = wait_until(lambda: any(k2 == "reconectado" for _, k2, _ in events[ev_start:]), 20)
            t_back = next((t for t, k2, _ in events[ev_start:] if k2 == "reconectado"), None)
            lost_t = next((t for t, k2, _ in events[ev_start:] if k2 == "perdido"), None)
            r = send_and_wait(1 + i)
            recov.append({
                "deteccion_s": round(lost_t - t_stop, 2) if lost_t else None,
                "reconexion_tras_reanudar_s": round(t_back - (t_stop + 5), 2) if t_back else None,
                "sin_servicio_s": round(t_back - t_stop, 2) if t_back else None,
                "intentos": sum(1 for _, k2, _ in events[ev_start:] if k2 == "reintento"),
                "pose_despues_ok": bool(r and r["ok"]),
                "reconecto": ok,
            })
            time.sleep(1)
        results["S5"] = recov

        # ---------------------------------------------------------
        # S6. Robot sin respuesta (congelado) 6 s, 5 veces:
        #     la conexión sigue abierta pero nadie contesta
        # ---------------------------------------------------------
        label("S6 robot sin respuesta")
        frz = []
        for i in range(5):
            ev_start = len(events)
            t_freeze = time.monotonic()
            maestro.frozen = True
            wait_until(lambda: any(k2 == "perdido" for _, k2, _ in events[ev_start:]), 10)
            lost_t = next((t for t, k2, _ in events[ev_start:] if k2 == "perdido"), None)
            remaining = 6 - (time.monotonic() - t_freeze)
            if remaining > 0:
                time.sleep(remaining)
            maestro.frozen = False
            t_unfreeze = time.monotonic()
            ok = wait_until(lambda: any(k2 == "reconectado" for _, k2, _ in events[ev_start:]), 25)
            t_back = next((t for t, k2, _ in events[ev_start:] if k2 == "reconectado"), None)
            r = send_and_wait(1 + i)
            frz.append({
                "deteccion_s": round(lost_t - t_freeze, 2) if lost_t else None,
                "sin_servicio_s": round(t_back - t_freeze, 2) if t_back else None,
                "reconexion_tras_responder_s": round(t_back - t_unfreeze, 2) if t_back else None,
                "pose_despues_ok": bool(r and r["ok"]),
                "reconecto": ok,
            })
            time.sleep(1)
        results["S6"] = frz

        # ---------------------------------------------------------
        # S7. Reglas del robot con un cliente crudo (sin la GUI):
        #     duplicados, CRC dañado y estado seguro a los 3 s
        # ---------------------------------------------------------
        label("S7 reglas del maestro")
        link.disconnect_device()
        wait_until(lambda: not link.connected, 3)
        time.sleep(0.5)

        s = raw_client()
        time.sleep(0.2)
        e0 = len(maestro.executions)
        f = p.build_frame(p.TYPE_POSE, 77, p.pose_payload(3))
        raw_send(s, f)
        time.sleep(0.2)
        raw_send(s, f)                      # reintento con el mismo SEQ
        time.sleep(0.3)
        r1 = raw_recv(s)
        dup = {
            "acks": sum(1 for fr in r1 if fr.type == p.TYPE_ACK),
            "ejecuciones": len(maestro.executions) - e0,
        }

        bad = bytearray(p.build_frame(p.TYPE_POSE, 78, p.pose_payload(2)))
        bad[-1] ^= 0x5A                     # CRC dañado
        raw_send(s, bytes(bad))
        time.sleep(0.3)
        r2 = raw_recv(s)
        crc = {
            "respuesta": [p.TYPE_NAMES.get(fr.type, hex(fr.type)) for fr in r2],
            "error": [p.ERROR_NAMES.get(fr.payload[2], "?") for fr in r2 if fr.type == p.TYPE_NACK],
            "ejecuciones": len(maestro.executions) - e0 - dup["ejecuciones"],
        }

        raw_send(s, p.build_frame(p.TYPE_POSE, 79, p.pose_payload(4)))
        t_last = time.monotonic()
        raw_recv(s)
        n_safe = len(maestro.safe_events)
        wait_until(lambda: len(maestro.safe_events) > n_safe, 6)
        t_safe = maestro.safe_events[-1][0] if len(maestro.safe_events) > n_safe else None
        results["S7"] = {
            "duplicado": dup,
            "crc_dañado": crc,
            "estado_seguro_s": round(t_safe - t_last, 2) if t_safe else None,
            "estado_seguro_motivo": maestro.safe_events[-1][1] if t_safe else None,
        }
        s.close()

    except Exception as error:
        import traceback
        results["error"] = traceback.format_exc()
        log("ERROR", error)

    finally:
        results["stats_enlace"] = dict(link.stats)
        finish()


def finish():
    try:
        link.shutdown()
    except Exception:
        pass
    results["resumen_md"] = session.close({"Webots": results.get("stats_enlace", {})})
    with open(os.path.join(OUT, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    try:
        maestro.stop()
    except Exception:
        pass
    # quit() es seguro desde otro hilo en Qt 6
    app.quit()


threading.Thread(target=scenario, daemon=True).start()
app.exec()
_real_print(f"Listo. Resultados en {OUT}")
