// =============================================
// PATRONES DEL MÓDULO POR POSTURA - SOFIA (Webots)
// =============================================
//
// Las figuras las forma EL MÓDULO COMPLETO, igual que en el ESP32
// (ESP32/sofia_maestro/movimiento.h): cada figura tiene un GRUPO FIJO de
// unidades (las que quedan sobre la figura) y una "esfera" virtual
// recorre la figura a velocidad constante. Las unidades del grupo
// SIGUEN a la esfera como en el tracking (se inclinan hacia ella), así
// que el movimiento es continuo. Solo se mueven las SIMULTANEAS (3) del
// grupo más cercanas a la esfera; el relevo entre la que sale y la que
// entra es gradual.
//
// Coordenadas de la CÁMARA CENITAL:
//
//     u = derecha en la imagen   ->  joint_1 (theta_1)
//     v = arriba en la imagen    ->  joint_3 + joint_2 (theta_2)
//
// Numeración de las unidades (como el módulo real):
//
//        13  14  15  16      fila de arriba
//      9  10  11  12
//        5   6   7   8
//      1   2   3   4         fila de abajo
//
// En sofia.wbt el panel "Panel_<fila>_<columna>" tiene la columna 0 a
// la DERECHA de la cámara, así que es la unidad fila*4 + (3 - columna) + 1.
//
//   INICIO   arriba-abajo por el centro
//   RECARGAR círculo de carga, como antes: una cabeza gira por el borde
//            en sentido horario (2 vueltas) y las unidades del borde se
//            inclinan hacia afuera con una cola que se apaga. Solo se
//            mueven las SIMULTANEAS más inclinadas
//   ESCUDO   rombo
//   ATAQUE   una L
//   FIN      izquierda-derecha (despedida)
//
// Al terminar, el panel vuelve a apuntar a la esfera de la mano (la
// ESFERA_TARGET del mundo, que no es la esfera virtual de las figuras).

#pragma once

#include <algorithm>
#include <cmath>

namespace patrones {

// Inclinación máxima de un patrón (rad). El tope seguro es 0.48.
const double AMPLITUD = 0.35;   // 20 grados, igual que el ESP32

// Cuántas unidades se mueven a la vez en una figura
const int SIMULTANEAS = 3;

struct Punto {
    double u;
    double v;
};

// Camino de la esfera, de -1 a 1 (1 = borde del arreglo)
const Punto FIG_INICIO[] = {{0, 0}, {0, 1}, {0, -1}, {0, 0}};
const Punto FIG_ESCUDO[] = {{0, 1}, {1, 0}, {0, -1}, {-1, 0}, {0, 1}};
const Punto FIG_ATAQUE[] = {{-0.5, 1}, {-0.5, -1}, {0.8, -1}};
const Punto FIG_FIN[] = {{-1, 0}, {1, 0}, {-1, 0}, {1, 0}};

const double TAM_FIGURA_U = 0.2345;   // medio ancho del arreglo (m)
const double TAM_FIGURA_V = 0.1741;   // medio alto del arreglo (m)

// Velocidad de la esfera (m/s)
//                            -  INICIO  RECARGAR  ESCUDO  ATAQUE  FIN
const double VEL_ESFERA[6] = {0, 0.350,  0,        0.550,  0.360,  0.470};

// Grupo fijo de cada figura (unidades a menos de ~85 mm del camino)
const int GRUPO_INICIO[] = {3, 6, 11, 14};
const int GRUPO_ESCUDO[] = {2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15};
const int GRUPO_ATAQUE[] = {2, 3, 4, 5, 6, 10, 13, 14};
const int GRUPO_FIN[] = {5, 6, 7, 8, 9, 10, 11, 12};

// Cómo sigue cada unidad a la esfera (m)
const double DIST_LLENA = 0.070;     // más lejos que esto: inclinada completa
const double RADIO_LLENO = 0.100;    // se apaga entre RADIO_LLENO...
const double RADIO_ESFERA = 0.200;   // ...y RADIO_ESFERA
const double RELEVO = 0.070;         // relevo gradual con la unidad que entra

// RECARGAR: "cabeza" que gira en sentido horario por el borde
const double RECARGA_VUELTA_S = 1.2;   // segundos por vuelta
const int RECARGA_VUELTAS = 2;
const double RECARGA_COLA = 2.2;       // rad de "cola" encendida detrás de la cabeza

#define SOFIA_N(a) ((int)(sizeof(a) / sizeof(a[0])))

inline void figura(int postura, const Punto *&fig, int &n, const int *&grupo, int &ng) {
    switch (postura) {
        case 1: fig = FIG_INICIO; n = SOFIA_N(FIG_INICIO); grupo = GRUPO_INICIO; ng = SOFIA_N(GRUPO_INICIO); break;
        case 3: fig = FIG_ESCUDO; n = SOFIA_N(FIG_ESCUDO); grupo = GRUPO_ESCUDO; ng = SOFIA_N(GRUPO_ESCUDO); break;
        case 4: fig = FIG_ATAQUE; n = SOFIA_N(FIG_ATAQUE); grupo = GRUPO_ATAQUE; ng = SOFIA_N(GRUPO_ATAQUE); break;
        case 5: fig = FIG_FIN;    n = SOFIA_N(FIG_FIN);    grupo = GRUPO_FIN;    ng = SOFIA_N(GRUPO_FIN);    break;
        default: fig = nullptr; n = 0; grupo = nullptr; ng = 0; break;
    }
}

// Posición de la unidad (1-16) vista desde el centro del arreglo, en la
// imagen cenital (m). Mismas posiciones que los paneles de sofia.wbt
inline void posicion(int unidad, double &u, double &v) {
    const double FILAS_X[4] = {-0.1741, -0.0580, 0.0580, 0.1741};
    // Como el módulo real: 134 mm entre centros y las filas 2 y 4
    // (unidades 5-8 y 13-16) corridas 67 mm a la derecha
    int k = unidad - 1;
    int fila = k / 4;
    int columna = k % 4;
    u = -0.2345 + 0.067 * (fila % 2) + 0.134 * columna;
    v = FILAS_X[fila];
}

// Unidad (1-16) del panel "Panel_<fila>_<columna>"
inline int unidad_del_panel(int fila, int columna) {
    return fila * 4 + (3 - columna) + 1;
}

inline bool en_borde(int unidad) {
    int k = unidad - 1, fila = k / 4, columna = k % 4;
    return fila == 0 || fila == 3 || columna == 0 || columna == 3;
}

// RECARGAR: qué tanto se inclina la unidad (0-1) a los t segundos
inline double intensidad_recarga(int unidad, double t) {
    if (!en_borde(unidad)) return 0;
    double u, v;
    posicion(unidad, u, v);
    double angulo = std::atan2(v, u);
    double cabeza = -2.0 * 3.14159265358979323846 * t / RECARGA_VUELTA_S;   // sentido horario
    double atras = std::fmod(angulo - cabeza, 2.0 * 3.14159265358979323846);
    if (atras < 0) atras += 2.0 * 3.14159265358979323846;
    // La cola se acorta para que quepan SIMULTANEAS unidades del borde
    // (12 = una cada 2π/12 rad) y la última se apague antes de que entre otra
    double cola = std::min(RECARGA_COLA, (SIMULTANEAS - 0.5) * 2.0 * 3.14159265358979323846 / 12.0);
    return atras < cola ? 1.0 - atras / cola : 0.0;
}

inline bool recarga(double t, int unidad, Punto &salida) {
    if (t > RECARGA_VUELTA_S * RECARGA_VUELTAS) return false;
    double mia = intensidad_recarga(unidad, t);
    if (mia <= 0) return true;

    // Solo las SIMULTANEAS más inclinadas (las más cercanas a la cabeza)
    int mas_inclinadas = 0;
    for (int k = 1; k <= 16; k++) {
        if (k == unidad) continue;
        double otra = intensidad_recarga(k, t);
        if (otra > mia || (otra == mia && k < unidad)) mas_inclinadas++;
    }
    if (mas_inclinadas >= SIMULTANEAS) return true;

    // Inclinarse hacia afuera del arreglo
    double u, v;
    posicion(unidad, u, v);
    double norma = std::hypot(u, v);
    salida.u = AMPLITUD * mia * u / norma;
    salida.v = AMPLITUD * mia * v / norma;
    return true;
}

// Patrón de la postura (1-5) para la unidad (1-16), t segundos después
// de empezar. Regresa false si la postura no existe o ya terminó.
inline bool patron(int postura, double t, int unidad, Punto &salida) {
    salida.u = 0;
    salida.v = 0;

    if (postura == 2) return recarga(t, unidad, salida);

    const Punto *fig;
    const int *grupo;
    int n, ng;
    figura(postura, fig, n, grupo, ng);
    if (n == 0) return false;

    // Dónde va la esfera
    double recorrido = VEL_ESFERA[postura] * t, eu = 0, ev = 0;
    bool sigue = false;
    for (int i = 1; i < n; i++) {
        double au = fig[i - 1].u * TAM_FIGURA_U, av = fig[i - 1].v * TAM_FIGURA_V;
        double bu = fig[i].u * TAM_FIGURA_U, bv = fig[i].v * TAM_FIGURA_V;
        double tramo = std::hypot(bu - au, bv - av);
        if (recorrido <= tramo) {
            double f = tramo > 0 ? recorrido / tramo : 1.0;
            eu = au + f * (bu - au);
            ev = av + f * (bv - av);
            sigue = true;
            break;
        }
        recorrido -= tramo;
    }
    if (!sigue) return false;

    bool en_grupo = false;
    for (int k = 0; k < ng; k++) en_grupo = en_grupo || grupo[k] == unidad;
    if (!en_grupo) return true;

    // Solo las SIMULTANEAS más cercanas a la esfera
    double pu, pv;
    posicion(unidad, pu, pv);
    double d = std::hypot(eu - pu, ev - pv);
    int mas_cercanas = 0;
    double otras[16];
    int no = 0;
    for (int k = 0; k < ng; k++) {
        if (grupo[k] == unidad) continue;
        double qu, qv;
        posicion(grupo[k], qu, qv);
        double dq = std::hypot(eu - qu, ev - qv);
        if (dq < d || (dq == d && grupo[k] < unidad)) mas_cercanas++;
        otras[no++] = dq;
    }
    if (mas_cercanas >= SIMULTANEAS) return true;

    // Relevo: se apaga conforme se le acerca la primera que queda fuera
    double relevo = 1.0;
    if (no >= SIMULTANEAS) {
        std::sort(otras, otras + no);
        relevo = std::min(1.0, std::max(0.0, (otras[SIMULTANEAS - 1] - d) / RELEVO));
    }

    // Inclinarse HACIA la esfera (como el tracking)
    double envolvente = std::min(1.0, std::max(0.0, (RADIO_ESFERA - d) / (RADIO_ESFERA - RADIO_LLENO)));
    double escala = AMPLITUD * envolvente * relevo / std::max(d, DIST_LLENA);
    salida.u = (eu - pu) * escala;
    salida.v = (ev - pv) * escala;
    return true;
}

#undef SOFIA_N

}  // namespace patrones
