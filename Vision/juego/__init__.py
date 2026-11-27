"""
juego/ - Vaquerito (demo) contra el robot

Toda la lógica del juego vive en la PC; el robot (ESP32 / Webots) solo
dibuja figuras: la jugada del robot en cada ronda (RECARGAR, ESCUDO,
ATAQUE) y una reacción al final (GANA o PIERDE).

    reglas.py   Qué pasa en una ronda (balas, quién gana)
    cpu.py      Cómo elige el robot: estrategia por estado + "dados" (2d6)
    partida.py  Máquina de estados de la partida (cuenta, espera, rondas)

No dependen de Qt: se pueden probar solos (python -m juego.partida).
"""
