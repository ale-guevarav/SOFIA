"""
REGISTRO DE SESIÓN DE LA GUI - SOFIA

Guarda la evidencia de las pruebas del ciclo detección -> acción y de
las pruebas de estrés, sin que el usuario tenga que anotar nada.

Cada vez que se abre la GUI se crea (al primer evento) la carpeta:

    metrics/sesiones/sesion_AAAAMMDD_HHMMSS/
        posturas.csv    cada cambio de postura detectada
        comandos.csv    cada comando enviado y su resultado (ACK, NACK,
                        sin respuesta), con la latencia del ciclo
        eventos.csv     conexiones, caídas, reconexiones, fallas de
                        cámara y errores
        bitacora.txt    copia de la bitácora de la GUI con la hora
        resumen.md      tablas listas para el reporte (al cerrar o con
        resumen.json    el botón "Guardar resumen")

ETIQUETA DE PRUEBA
------------------
En la GUI se escribe la condición que se está probando (ej. "luz baja",
"2 personas", "cambios rápidos"). Cada fila lleva esa etiqueta y el
resumen separa los resultados por etiqueta: así cada condición de la
prueba de estrés sale en su propia fila de la tabla.

LATENCIAS
---------
    rtt_ms    envío de la trama -> ACK (último intento)
    cola_ms   la GUI pide el comando -> ACK (incluye esperar en la cola
              y los reintentos)
    ciclo_ms  procesamiento del frame + cola_ms: desde que se tomó la
              imagen hasta que el ESP32 confirmó la acción

Todo corre en el hilo de la GUI; escribir unas filas de CSV tarda
microsegundos y no afecta el video.
"""

import csv
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime


BASE_DIR = os.path.join("metrics", "sesiones")


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q / 100 * (len(ordered) - 1))))
    return ordered[index]


def _fmt(value, digits=0):
    return "--" if value is None else f"{value:.{digits}f}"


class SessionLogger:

    FILES = {
        "posturas": ["t_s", "hora", "etiqueta", "postura", "persona", "proc_ms"],
        "comandos": [
            "t_s", "hora", "etiqueta", "destino", "comando", "postura", "seq",
            "ok", "intentos", "rtt_ms", "cola_ms", "ciclo_ms", "detalle",
        ],
        "eventos": ["t_s", "hora", "etiqueta", "origen", "tipo", "detalle"],
    }


    def __init__(self, base_dir=BASE_DIR):

        self.base_dir = base_dir
        self.folder = None

        self.label = ""
        self._t0 = time.monotonic()
        self._started = datetime.now()

        self._files = {}
        self._writers = {}
        self._log_file = None
        self._closed = False

        # Copia en memoria para el resumen
        self._rows = defaultdict(list)


    # =============================================
    # ARCHIVOS (se crean al primer evento)
    # =============================================

    def _ensure_folder(self):

        if self.folder is None:
            name = self._started.strftime("sesion_%Y%m%d_%H%M%S")
            self.folder = os.path.join(self.base_dir, name)
            os.makedirs(self.folder, exist_ok=True)

        return self.folder


    def _write(self, kind, row):

        if self._closed:
            return

        if kind not in self._writers:
            path = os.path.join(self._ensure_folder(), f"{kind}.csv")
            handle = open(path, "w", newline="", encoding="utf-8")
            writer = csv.DictWriter(handle, fieldnames=self.FILES[kind])
            writer.writeheader()
            self._files[kind] = handle
            self._writers[kind] = writer

        base = {
            "t_s": f"{time.monotonic() - self._t0:.3f}",
            "hora": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "etiqueta": self.label,
        }
        base.update(row)

        self._writers[kind].writerow(base)
        # flush: si la PC se apaga, lo escrito no se pierde
        self._files[kind].flush()
        self._rows[kind].append(base)


    # =============================================
    # API PARA LA GUI
    # =============================================

    def set_label(self, label):
        label = label.strip()
        if label != self.label:
            self.label = label
            self.event("gui", "etiqueta", label or "(sin etiqueta)")


    def posture(self, gesture, person_detected, processing_ms):
        self._write("posturas", {
            "postura": gesture,
            "persona": int(bool(person_detected)),
            "proc_ms": f"{processing_ms:.1f}",
        })


    def command(self, target, info):
        """info: el dict de BleLink.command_done."""

        tag = info.get("tag") or {}
        cycle_ms = None

        if "proc_ms" in tag and info.get("ok"):
            cycle_ms = tag["proc_ms"] + info["cola_ms"]

        self._write("comandos", {
            "destino": target,
            "comando": info["comando"],
            "postura": tag.get("postura", ""),
            "seq": "" if info["seq"] is None else info["seq"],
            "ok": int(bool(info["ok"])),
            "intentos": info["intentos"],
            "rtt_ms": _fmt(info["rtt_ms"], 1) if info["rtt_ms"] is not None else "",
            "cola_ms": f"{info['cola_ms']:.1f}",
            "ciclo_ms": "" if cycle_ms is None else f"{cycle_ms:.1f}",
            "detalle": info["detalle"],
        })


    def event(self, origin, kind, detail=""):
        self._write("eventos", {"origen": origin, "tipo": kind, "detalle": detail})


    def log_line(self, text):

        if self._closed:
            return

        if self._log_file is None:
            path = os.path.join(self._ensure_folder(), "bitacora.txt")
            self._log_file = open(path, "a", encoding="utf-8")

        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_file.write(f"{stamp}  {text}\n")
        self._log_file.flush()


    # =============================================
    # RESUMEN
    # =============================================

    def summary(self, link_stats=None):
        """Escribe resumen.md y resumen.json. Regresa la ruta del .md (o None)."""

        if self.folder is None:
            return None

        data = {
            "inicio": self._started.isoformat(timespec="seconds"),
            "duracion_s": round(time.monotonic() - self._t0, 1),
            "por_etiqueta": {},
            "eventos": dict(Counter(
                f"{r['origen']}:{r['tipo']}" for r in self._rows["eventos"]
            )),
            "enlaces": link_stats or {},
        }

        labels = sorted(
            {r["etiqueta"] for kind in ("posturas", "comandos") for r in self._rows[kind]}
        )

        for label in labels:
            data["por_etiqueta"][label or "(sin etiqueta)"] = self._label_summary(label)

        data["caidas"] = self._downtime_summary()

        with open(os.path.join(self.folder, "resumen.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        path = os.path.join(self.folder, "resumen.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._markdown(data))

        return path


    def _label_summary(self, label):

        postures = [r for r in self._rows["posturas"] if r["etiqueta"] == label]
        commands = [
            r for r in self._rows["comandos"]
            if r["etiqueta"] == label and r["comando"] == "POSE"
        ]

        detected = Counter(
            r["postura"] for r in postures if r["postura"] not in ("---", "")
        )

        targets = {}

        for target in sorted({r["destino"] for r in commands}):
            rows = [r for r in commands if r["destino"] == target]
            ok = [r for r in rows if r["ok"] == 1]
            cycles = [float(r["ciclo_ms"]) for r in ok if r["ciclo_ms"] != ""]
            rtts = [float(r["rtt_ms"]) for r in ok if r["rtt_ms"] != ""]
            retries = [int(r["intentos"]) for r in rows if r["intentos"]]

            per_pose = {}
            for pose in sorted({r["postura"] for r in rows}):
                pose_rows = [r for r in rows if r["postura"] == pose]
                per_pose[pose] = {
                    "enviados": len(pose_rows),
                    "ack": sum(r["ok"] for r in pose_rows),
                }

            targets[target] = {
                "enviados": len(rows),
                "ack": len(ok),
                "exito_pct": round(100 * len(ok) / len(rows), 1) if rows else None,
                "intentos_prom": round(statistics.mean(retries), 2) if retries else None,
                "rtt_ms_prom": round(statistics.mean(rtts), 1) if rtts else None,
                "ciclo_ms_prom": round(statistics.mean(cycles), 1) if cycles else None,
                "ciclo_ms_p95": round(_percentile(cycles, 95), 1) if cycles else None,
                "ciclo_ms_max": round(max(cycles), 1) if cycles else None,
                "fallas": dict(Counter(r["detalle"] for r in rows if r["ok"] == 0)),
                "por_postura": per_pose,
            }

        return {
            "cambios_de_postura": len(postures),
            "posturas_detectadas": dict(detected),
            "destinos": targets,
        }


    def _downtime_summary(self):

        result = {}

        for r in self._rows["eventos"]:
            if r["tipo"] in ("reconectado", "recuperada"):
                entry = result.setdefault(r["origen"], [])
                try:
                    entry.append(float(r["detalle"]))
                except ValueError:
                    pass

        return {
            origin: {
                "recuperaciones": len(values),
                "sin_servicio_prom_s": round(statistics.mean(values), 1),
                "sin_servicio_max_s": round(max(values), 1),
            }
            for origin, values in result.items() if values
        }


    @staticmethod
    def _markdown(data):

        lines = [
            "# Resumen de la sesión",
            "",
            f"- Inicio: {data['inicio']}",
            f"- Duración: {data['duracion_s']:.0f} s",
            "",
            "## Comandos de postura por condición",
            "",
            "| Condición | Destino | Enviados | ACK | Éxito | Intentos prom. "
            "| RTT prom. (ms) | Ciclo prom. (ms) | Ciclo p95 (ms) | Ciclo máx. (ms) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]

        for label, info in data["por_etiqueta"].items():
            for target, t in info["destinos"].items():
                lines.append(
                    f"| {label} | {target} | {t['enviados']} | {t['ack']} | "
                    f"{_fmt(t['exito_pct'], 1)} % | {_fmt(t['intentos_prom'], 2)} | "
                    f"{_fmt(t['rtt_ms_prom'], 1)} | {_fmt(t['ciclo_ms_prom'], 1)} | "
                    f"{_fmt(t['ciclo_ms_p95'], 1)} | {_fmt(t['ciclo_ms_max'], 1)} |"
                )

        lines += [
            "",
            "## Posturas detectadas por condición",
            "",
            "| Condición | Cambios | INICIO | RECARGAR | ESCUDO | ATAQUE | FIN |",
            "|---|---|---|---|---|---|---|",
        ]

        for label, info in data["por_etiqueta"].items():
            d = info["posturas_detectadas"]
            lines.append(
                f"| {label} | {info['cambios_de_postura']} | "
                + " | ".join(str(d.get(g, 0)) for g in
                             ("INICIO", "RECARGAR", "ESCUDO", "ATAQUE", "FIN"))
                + " |"
            )

        failures = [
            (label, target, reason, count)
            for label, info in data["por_etiqueta"].items()
            for target, t in info["destinos"].items()
            for reason, count in t["fallas"].items()
        ]

        if failures:
            lines += ["", "## Comandos fallidos", "",
                      "| Condición | Destino | Causa | Veces |", "|---|---|---|---|"]
            lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in failures]

        lines += ["", "## Eventos", "", "| Evento | Veces |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(data["eventos"].items())]

        if data["caidas"]:
            lines += ["", "## Recuperación ante fallas", "",
                      "| Origen | Recuperaciones | Sin servicio prom. (s) | Máx. (s) |",
                      "|---|---|---|---|"]
            for origin, c in data["caidas"].items():
                lines.append(
                    f"| {origin} | {c['recuperaciones']} | "
                    f"{c['sin_servicio_prom_s']} | {c['sin_servicio_max_s']} |"
                )

        if data["enlaces"]:
            lines += ["", "## Contadores de los enlaces", ""]
            names = sorted({k for stats in data["enlaces"].values() for k in stats})
            lines.append("| Enlace | " + " | ".join(names) + " |")
            lines.append("|---" * (len(names) + 1) + "|")
            for link, stats in data["enlaces"].items():
                lines.append(
                    f"| {link} | " + " | ".join(str(stats.get(n, 0)) for n in names) + " |"
                )

        return "\n".join(lines) + "\n"


    def close(self, link_stats=None):

        path = self.summary(link_stats)
        self._closed = True

        for handle in self._files.values():
            handle.close()
        self._files.clear()
        self._writers.clear()

        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

        return path
