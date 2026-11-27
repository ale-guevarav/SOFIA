"""
CPU DEL VAQUERITO - SOFIA

El robot no elige 1 de 3 al azar. Tiene una ESTRATEGIA POR ESTADO (según
cuántas balas tiene él y cuántas su rival) y en cada estado "tira dos
dados de 6" (2d6, suma de 2 a 12). Como con dos dados el 7 sale mucho
más que el 2 o el 12, cada tabla pone la jugada sensata en el centro y
las "confusiones" en las orillas:

    suma:   2   3   4   5   6   7   8   9  10  11  12
    de 36:  1   2   3   4   5   6   5   4   3   2   1

Estados:

    AMBOS_SIN_BALAS  nadie puede disparar      -> casi siempre recarga
    RIVAL_ARMADO     él sin balas, rival sí    -> sobre todo se cubre, a veces
                                                  recarga, y solo con un 12
                                                  "se confunde" y dispara (NULO)
    SOLO_YO_ARMADO   él sí, el rival no        -> dispara o sigue juntando balas
    AMBOS_ARMADOS    los dos tienen            -> dispara seguido, o se cubre
    RIVAL_CARGADO    los dos tienen, pero el   -> más cauteloso: se cubre
                     rival le lleva 2 o más

Con el cargador lleno (6) no tiene caso recargar: esa jugada se cambia
por ATAQUE si el rival no tiene balas o por ESCUDO si sí tiene.

Las tablas se pueden ajustar aquí mismo: cada fila es (de, hasta, jugada).
"""

import itertools
import random

from .reglas import ATAQUE, ESCUDO, MAX_BALAS, RECARGAR


AMBOS_SIN_BALAS = "AMBOS_SIN_BALAS"
RIVAL_ARMADO = "RIVAL_ARMADO"
SOLO_YO_ARMADO = "SOLO_YO_ARMADO"
AMBOS_ARMADOS = "AMBOS_ARMADOS"
RIVAL_CARGADO = "RIVAL_CARGADO"

DADOS = 2       # cuántos dados
CARAS = 6       # de cuántas caras

TABLAS = {
    AMBOS_SIN_BALAS: [
        (2, 10, RECARGAR),     # 33/36
        (11, 11, ESCUDO),      #  2/36
        (12, 12, ATAQUE),      #  1/36 (se confunde: sale NULO)
    ],
    RIVAL_ARMADO: [
        (2, 4, RECARGAR),      #  6/36
        (5, 9, ESCUDO),        # 24/36
        (10, 11, RECARGAR),    #  5/36
        (12, 12, ATAQUE),      #  1/36 (se confunde: sale NULO)
    ],
    SOLO_YO_ARMADO: [
        (2, 2, ESCUDO),        #  1/36
        (3, 5, RECARGAR),      #  9/36
        (6, 8, ATAQUE),        # 16/36
        (9, 10, RECARGAR),     #  7/36
        (11, 12, ESCUDO),      #  3/36
    ],
    AMBOS_ARMADOS: [
        (2, 3, RECARGAR),      #  3/36
        (4, 5, ESCUDO),        #  7/36
        (6, 8, ATAQUE),        # 16/36
        (9, 10, ESCUDO),       #  7/36
        (11, 12, RECARGAR),    #  3/36
    ],
    RIVAL_CARGADO: [
        (2, 2, RECARGAR),      #  1/36
        (3, 4, ATAQUE),        #  5/36
        (5, 9, ESCUDO),        # 24/36
        (10, 11, ATAQUE),      #  5/36
        (12, 12, RECARGAR),    #  1/36
    ],
}


def estado(mis_balas, balas_rival):
    if mis_balas == 0:
        return RIVAL_ARMADO if balas_rival > 0 else AMBOS_SIN_BALAS
    if balas_rival == 0:
        return SOLO_YO_ARMADO
    if balas_rival >= mis_balas + 2:
        return RIVAL_CARGADO
    return AMBOS_ARMADOS


def jugada_de_tabla(tabla, tirada):
    for desde, hasta, jugada in tabla:
        if desde <= tirada <= hasta:
            return jugada
    raise ValueError(f"La tirada {tirada} no está en la tabla")


class CPU:

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def tirar(self):
        return sum(self.rng.randint(1, CARAS) for _ in range(DADOS))

    def elegir(self, mis_balas, balas_rival):
        """Regresa (jugada, estado, tirada). La jugada ya cuenta el
        cargador lleno; si es ATAQUE sin balas, las reglas la vuelven NULO."""
        situacion = estado(mis_balas, balas_rival)
        tirada = self.tirar()
        jugada = jugada_de_tabla(TABLAS[situacion], tirada)
        if jugada == RECARGAR and mis_balas >= MAX_BALAS:
            jugada = ATAQUE if balas_rival == 0 else ESCUDO
        return jugada, situacion, tirada


def probabilidades(situacion):
    """Probabilidad de cada jugada en un estado (para revisar las tablas)."""
    formas = {}
    for dados in itertools.product(range(1, CARAS + 1), repeat=DADOS):
        formas[sum(dados)] = formas.get(sum(dados), 0) + 1
    total = CARAS ** DADOS
    salida = {}
    for tirada, n in formas.items():
        jugada = jugada_de_tabla(TABLAS[situacion], tirada)
        salida[jugada] = salida.get(jugada, 0) + n / total
    return salida
