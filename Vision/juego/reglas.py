"""
REGLAS DEL VAQUERITO - SOFIA

Como piedra, papel o tijera: los dos eligen al mismo tiempo una jugada.

    RECARGAR  +1 bala (máximo MAX_BALAS; si ya tiene 6 se queda en 6)
    ESCUDO    se cubre esa ronda; no da nada ni se acumula
    ATAQUE    dispara; gasta 1 bala. Sin balas no sale nada: es NULO

Solo se gana disparándole al otro mientras recarga (o mientras hace un
disparo NULO, que lo deja igual de expuesto):

    Tú \\ Rival   RECARGAR          ESCUDO              ATAQUE
    RECARGAR     los dos +1        tú +1               PIERDES
    ESCUDO       rival +1          nada                bloqueas (gasta su bala)
    ATAQUE       GANAS             te bloquea          se cancelan (los dos gastan)

La partida termina en cuanto alguien recibe un disparo.
"""

from dataclasses import dataclass


RECARGAR = "RECARGAR"
ESCUDO = "ESCUDO"
ATAQUE = "ATAQUE"
NULO = "NULO"          # ATAQUE sin balas

JUGADAS = (RECARGAR, ESCUDO, ATAQUE)

MAX_BALAS = 6

JUGADOR = "JUGADOR"
ROBOT = "ROBOT"


@dataclass
class Resolucion:
    jugada_jugador: str      # lo que hizo de verdad (ATAQUE puede volverse NULO)
    jugada_robot: str
    balas_jugador: int       # balas después de la ronda
    balas_robot: int
    ganador: str = None      # JUGADOR, ROBOT o None (la partida sigue)
    texto: str = ""          # qué pasó, para la pantalla


def efectiva(jugada, balas):
    """ATAQUE sin balas no dispara."""
    return NULO if jugada == ATAQUE and balas <= 0 else jugada


def resolver(jugada_jugador, jugada_robot, balas_jugador, balas_robot):
    """Aplica una ronda. Regresa las jugadas efectivas, las balas nuevas
    y, si alguien recibió un disparo, el ganador."""

    if jugada_jugador not in JUGADAS or jugada_robot not in JUGADAS:
        raise ValueError(f"Jugada inválida: {jugada_jugador} / {jugada_robot}")

    j = efectiva(jugada_jugador, balas_jugador)
    r = efectiva(jugada_robot, balas_robot)

    # Balas: recargar suma (con tope) y un disparo real gasta
    bj = min(MAX_BALAS, balas_jugador + 1) if j == RECARGAR else balas_jugador - (j == ATAQUE)
    br = min(MAX_BALAS, balas_robot + 1) if r == RECARGAR else balas_robot - (r == ATAQUE)

    # Expuesto = recargando o con un disparo NULO
    expuesto = (RECARGAR, NULO)

    if j == ATAQUE and r == ATAQUE:
        return Resolucion(j, r, bj, br, None, "¡Se cancelan los disparos!")
    if j == ATAQUE and r in expuesto:
        return Resolucion(j, r, bj, br, JUGADOR, "¡Le disparaste al robot!")
    if r == ATAQUE and j in expuesto:
        return Resolucion(j, r, bj, br, ROBOT, "¡El robot te disparó!")
    if j == ATAQUE and r == ESCUDO:
        return Resolucion(j, r, bj, br, None, "El robot bloqueó tu disparo")
    if r == ATAQUE and j == ESCUDO:
        return Resolucion(j, r, bj, br, None, "Bloqueaste el disparo")

    partes = []
    if j == NULO:
        partes.append("Disparaste sin balas")
    if r == NULO:
        partes.append("El robot disparó sin balas")
    if not partes:
        partes.append("Nadie disparó")
    return Resolucion(j, r, bj, br, None, " · ".join(partes))
