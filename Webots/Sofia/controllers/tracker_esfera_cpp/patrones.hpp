// =============================================
// PATRONES DE LOS PANELES POR POSTURA - SOFIA (Webots)
// =============================================
//
// Cada postura que detecta la visión se "dibuja" con las placas
// de las 16 unidades. Las coordenadas son las de la CÁMARA CENITAL:
//
//     u = derecha en la imagen   ->  joint_1 (theta_1)
//     v = arriba en la imagen    ->  joint_3 + joint_2 (theta_2)
//
//   INICIO   arriba-abajo, todos al unísono
//   RECARGAR "círculo de carga": solo los 12 paneles del borde,
//            uno tras otro, inclinándose hacia afuera
//   ESCUDO   rombo, todos al unísono
//   ATAQUE   una L, todos al unísono
//   FIN      izquierda-derecha (despedida), todos al unísono
//
// Al terminar, el panel vuelve a apuntar a la esfera.

#pragma once

#include <cmath>

namespace patrones {

const double PI = 3.14159265358979323846;

// Inclinación máxima de un patrón (rad). El tope seguro es 0.48.
const double AMPLITUD = 0.35;

struct Punto {
    double u;
    double v;
};

// Trayectoria: puntos (en unidades de AMPLITUD) unidos por
// rectas, recorridos a velocidad constante (unidades / s)
struct Trayectoria {
    const Punto *puntos;
    int n;
    double velocidad;
};

const Punto INICIO_P[] = {{0, 0}, {0, 1}, {0, -1}, {0, 0}};
const Punto ESCUDO_P[] = {{0, 0}, {0, 1}, {1, 0}, {0, -1}, {-1, 0}, {0, 1}, {0, 0}};
const Punto ATAQUE_P[] = {{0, 0}, {-0.5, 1}, {-0.5, -1}, {0.8, -1}, {0, 0}};
const Punto FIN_P[] = {{0, 0}, {-1, 0}, {1, 0}, {-1, 0}, {1, 0}, {0, 0}};

const Trayectoria INICIO = {INICIO_P, 4, 2.5};
const Trayectoria ESCUDO = {ESCUDO_P, 7, 2.5};
const Trayectoria ATAQUE = {ATAQUE_P, 5, 3.0};
const Trayectoria FIN = {FIN_P, 6, 3.5};

// RECARGAR: "cabeza" que gira en sentido horario por el borde
const double RECARGA_VUELTA_S = 1.2;   // segundos por vuelta
const int RECARGA_VUELTAS = 2;
const double RECARGA_COLA = 2.2;       // rad de "cola" encendida detrás de la cabeza


// Posición sobre la trayectoria t segundos después de empezar.
// Regresa false cuando ya terminó.
inline bool en_trayectoria(const Trayectoria &tr, double t, Punto &salida) {
    double recorrido = tr.velocidad * t;

    for (int i = 1; i < tr.n; i++) {
        const Punto &a = tr.puntos[i - 1];
        const Punto &b = tr.puntos[i];
        double tramo = std::hypot(b.u - a.u, b.v - a.v);

        if (recorrido <= tramo) {
            double f = tramo > 0 ? recorrido / tramo : 1.0;
            salida.u = AMPLITUD * (a.u + f * (b.u - a.u));
            salida.v = AMPLITUD * (a.v + f * (b.v - a.v));
            return true;
        }

        recorrido -= tramo;
    }

    salida.u = 0;
    salida.v = 0;
    return false;
}


// RECARGAR para un panel. (dir_u, dir_v) = dirección del panel
// vista desde el centro del arreglo (en la imagen cenital).
inline bool recarga(double t, double dir_u, double dir_v, bool en_borde, Punto &salida) {
    salida.u = 0;
    salida.v = 0;

    if (t > RECARGA_VUELTA_S * RECARGA_VUELTAS) {
        return false;
    }

    // Los 4 paneles del centro se quedan quietos
    if (!en_borde) {
        return true;
    }

    double norma = std::hypot(dir_u, dir_v);
    if (norma <= 0) {
        return true;
    }

    double angulo_panel = std::atan2(dir_v, dir_u);

    // Sentido horario: el ángulo de la cabeza disminuye
    double cabeza = -2.0 * PI * t / RECARGA_VUELTA_S;

    // Qué tan atrás de la cabeza va este panel (0 = justo en ella)
    double atras = std::fmod(angulo_panel - cabeza, 2.0 * PI);
    if (atras < 0) {
        atras += 2.0 * PI;
    }

    double intensidad = atras < RECARGA_COLA ? 1.0 - atras / RECARGA_COLA : 0.0;

    // Inclinarse hacia afuera del arreglo
    salida.u = AMPLITUD * intensidad * dir_u / norma;
    salida.v = AMPLITUD * intensidad * dir_v / norma;
    return true;
}


// Patrón de la postura (1-5) para este panel.
// Regresa false si la postura no existe o el patrón ya terminó.
inline bool patron(int postura, double t, double dir_u, double dir_v, bool en_borde,
                   Punto &salida) {
    switch (postura) {
        case 1: return en_trayectoria(INICIO, t, salida);
        case 2: return recarga(t, dir_u, dir_v, en_borde, salida);
        case 3: return en_trayectoria(ESCUDO, t, salida);
        case 4: return en_trayectoria(ATAQUE, t, salida);
        case 5: return en_trayectoria(FIN, t, salida);
        default: return false;
    }
}

}  // namespace patrones
