"""
PARTIDA DE VAQUERITO - SOFIA (máquina de estados)

    INACTIVA ──iniciar──► CUENTA ──3 × "¡VAQUERITO!"──► ESPERANDO
                            ▲                              │
                            │                    postura (RECARGAR/ESCUDO/ATAQUE)
                     siguiente ronda                       │        10 s sin postura
                            │                              ▼               │
                         RESULTADO ◄──nadie muere──── resolver ronda       ▼
                                                           │          INACTIVA
                                                   alguien muere     (cancelada)
                                                           ▼
                                                       TERMINADA

- El robot elige y GUARDA su jugada al empezar la cuenta, antes de que se
  lea la postura de la persona; nadie la ve hasta que se resuelve la ronda.
- La cuenta es para que la persona se prepare. Al terminar, se toma la
  primera postura válida que se vea; si en ESPERA_MAX_S no hay ninguna,
  la partida se cancela.

No depende de Qt: la GUI llama actualizar(ahora, postura) seguido (con un
QTimer) y reacciona a los eventos que regresa.
"""

import random
from dataclasses import dataclass, field

from .cpu import CPU
from .reglas import JUGADAS, resolver


INACTIVA = "INACTIVA"
CUENTA = "CUENTA"
ESPERANDO = "ESPERANDO"
RESULTADO = "RESULTADO"
TERMINADA = "TERMINADA"

VECES_VAQUERITO = 3
PASO_CUENTA_S = 0.9      # cada "¡VAQUERITO!"
ESPERA_MAX_S = 10.0      # sin postura en este tiempo se cancela
PAUSA_RESULTADO_S = 3.0  # se ve el resultado y el robot dibuja su jugada


@dataclass
class Ronda:
    numero: int
    jugada_jugador: str
    jugada_robot: str
    efectiva_jugador: str
    efectiva_robot: str
    balas_jugador: int       # después de la ronda
    balas_robot: int
    texto: str
    ganador: str = None
    estado_cpu: str = ""
    tirada: int = 0


@dataclass
class Evento:
    tipo: str                # "cuenta", "ya", "ronda", "fin", "cancelada"
    datos: dict = field(default_factory=dict)


class Partida:

    def __init__(self, cpu=None, rng=None):
        self.cpu = cpu or CPU(rng or random.Random())
        self.estado = INACTIVA
        self.reiniciar()

    def reiniciar(self):
        self.balas_jugador = 0
        self.balas_robot = 0
        self.ronda = 0
        self.rondas = []
        self.ganador = None
        self._t = 0.0
        self._cuenta_mostrada = 0
        self._oculta = None          # (jugada, estado_cpu, tirada) del robot

    @property
    def activa(self):
        return self.estado in (CUENTA, ESPERANDO, RESULTADO)

    # -----------------------------
    # TRANSICIONES
    # -----------------------------

    def iniciar(self, ahora):
        self.reiniciar()
        return self._nueva_ronda(ahora)

    def cancelar(self, motivo):
        if not self.activa:
            return []
        self.estado = INACTIVA
        self._oculta = None
        return [Evento("cancelada", {"motivo": motivo})]

    def _nueva_ronda(self, ahora):
        self.ronda += 1
        self.estado = CUENTA
        self._t = ahora
        self._cuenta_mostrada = 1
        # El robot decide YA y lo guarda sin mostrarlo
        self._oculta = self.cpu.elegir(self.balas_robot, self.balas_jugador)
        return [Evento("cuenta", {"n": 1, "ronda": self.ronda})]

    def actualizar(self, ahora, postura):
        """postura: la que se ve ahora (cualquier texto; solo cuentan las
        tres jugadas). Regresa la lista de eventos nuevos."""

        if self.estado == CUENTA:
            n = int((ahora - self._t) / PASO_CUENTA_S) + 1
            if n <= VECES_VAQUERITO:
                if n > self._cuenta_mostrada:
                    self._cuenta_mostrada = n
                    return [Evento("cuenta", {"n": n, "ronda": self.ronda})]
                return []
            self.estado = ESPERANDO
            self._t = ahora
            return [Evento("ya", {"ronda": self.ronda})]

        if self.estado == ESPERANDO:
            if postura in JUGADAS:
                return self._resolver(ahora, postura)
            if ahora - self._t > ESPERA_MAX_S:
                return self.cancelar(f"no se detectó ninguna jugada en {ESPERA_MAX_S:.0f} s")
            return []

        if self.estado == RESULTADO and ahora - self._t >= PAUSA_RESULTADO_S:
            return self._nueva_ronda(ahora)

        return []

    def _resolver(self, ahora, postura):
        jugada_robot, estado_cpu, tirada = self._oculta
        self._oculta = None
        r = resolver(postura, jugada_robot, self.balas_jugador, self.balas_robot)
        self.balas_jugador, self.balas_robot = r.balas_jugador, r.balas_robot

        ronda = Ronda(self.ronda, postura, jugada_robot, r.jugada_jugador, r.jugada_robot,
                      r.balas_jugador, r.balas_robot, r.texto, r.ganador, estado_cpu, tirada)
        self.rondas.append(ronda)
        eventos = [Evento("ronda", {"ronda": ronda})]

        if r.ganador:
            self.ganador = r.ganador
            self.estado = TERMINADA
            eventos.append(Evento("fin", {"ganador": r.ganador, "rondas": self.ronda}))
        else:
            self.estado = RESULTADO
            self._t = ahora
        return eventos


# =============================================
# PRUEBA EN CONSOLA: python -m juego.partida  (desde Vision/)
# Escribe r / e / a por ronda (Enter vacío = no hacer nada)
# =============================================

if __name__ == "__main__":
    nombres = {"r": "RECARGAR", "e": "ESCUDO", "a": "ATAQUE"}
    partida = Partida()
    t = 0.0
    for e in partida.iniciar(t):
        print(e)
    while partida.activa:
        t += 0.1
        eventos = partida.actualizar(t, None)
        for e in eventos:
            if e.tipo == "cuenta":
                print("¡VAQUERITO!" , e.datos["n"])
            elif e.tipo == "ya":
                print(f"Balas: tú {partida.balas_jugador} · robot {partida.balas_robot}")
                jugada = nombres.get(input("Tu jugada [r/e/a]: ").strip().lower())
                for f in partida.actualizar(t, jugada) if jugada else partida.cancelar("sin jugada"):
                    if f.tipo == "ronda":
                        ronda = f.datos["ronda"]
                        print(f"  tú {ronda.efectiva_jugador} · robot {ronda.efectiva_robot} "
                              f"(2d6={ronda.tirada}, {ronda.estado_cpu}) -> {ronda.texto}")
                    else:
                        print(" ", f.tipo, f.datos)
                t += PAUSA_RESULTADO_S
