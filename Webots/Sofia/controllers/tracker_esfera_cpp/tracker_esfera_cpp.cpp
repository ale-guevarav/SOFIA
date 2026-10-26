#include <webots/Supervisor.hpp>
#include <webots/Motor.hpp>
#include <webots/Node.hpp>
#include <webots/Field.hpp>
#include <cmath>
#include <algorithm>
#include <cstdio>
#include <iostream>
#include <string>

#include "patrones.hpp"

using namespace webots;

// Controlador de un panel 2-DOF que orienta su "palo" hacia la esfera.
// Corre igual en los 16 paneles. NINGUN panel mueve la esfera: solo LEE
//
// Ademas lee el campo customData de la esfera, donde el maestro
// (sofia_maestro_sim) escribe el modo y la ultima orden de la GUI:
//
//     "M<modo> IDLE" / "M<modo> TRACK" / "M<modo> POSE <postura> <inicio>"
//
//   - Modo TRACKING (M2): el panel apunta a la esfera.
//   - Modo JUEGO / TEST: ignora la esfera y se queda en 0,0.
//   - POSE: mientras dura el patron de esa postura, lo dibuja
//     (ver patrones.hpp) y despues regresa a lo anterior.

// Modo TRACKING en el protocolo
const int MODO_TRACKING = 2;

// Centro del arreglo 4x4 (promedio de las posiciones de los paneles)
const double CENTRO_X = 0.0;
const double CENTRO_Y = 0.035;

int main(int argc, char **argv) {
    Supervisor *robot = new Supervisor();
    int timeStep = (int)robot->getBasicTimeStep();

    Motor *motor_gdl1 = robot->getMotor("motor_gdl1");
    Motor *motor_gdl2 = robot->getMotor("motor_gdl2");
    if (!motor_gdl1 || !motor_gdl2) {
        std::cerr << "[" << robot->getName() << "] ERROR: motores no encontrados." << std::endl;
    }

    // Campo de posicion de la esfera (solo lectura desde aqui)
    Node *esfera_node = robot->getFromDef("ESFERA_TARGET");
    if (!esfera_node) {
        std::cerr << "[" << robot->getName() << "] ERROR: ESFERA_TARGET no encontrado." << std::endl;
    }
    Field *trans_field = esfera_node ? esfera_node->getField("translation") : nullptr;

    // Comando de postura que escribe el maestro
    Field *comando_field = esfera_node ? esfera_node->getField("customData") : nullptr;

    // Posicion global de este panel (para calcular su propio vector hacia la esfera)
    const double *my_pos = robot->getSelf()->getPosition();

    // -----------------------------
    // DATOS DEL PANEL PARA LOS PATRONES
    // -----------------------------

    // Fila y columna a partir del nombre "Panel_<fila>_<columna>"
    int fila = -1, columna = -1;
    std::sscanf(robot->getName().c_str(), "Panel_%d_%d", &fila, &columna);

    // Los 12 paneles del borde participan en RECARGAR
    bool en_borde = fila == 0 || fila == 3 || columna == 0 || columna == 3;

    std::string ultimo_comando;
    int modo = 0;            // sin maestro: como JUEGO (paneles en 0,0)
    int postura_activa = 0;
    double inicio_patron = 0.0;

    // Angulos aplicados a los motores (se acercan poco a poco al objetivo, ver abajo)
    double theta_1_actual = 0.0;
    double theta_2_actual = 0.0;

    const double K_SUAVIZADO = 0.15;     // que tan rapido reacciona el panel (0-1)
    const double MAX_PASO = 0.15;        // rad, tope de cambio por paso (evita saltos)
    const double LIMITE_SEGURO = 0.48;   // rad, margen bajo el tope mecanico (0.5235)

    while (robot->step(timeStep) != -1) {

        // 0) Nuevo comando de postura?
        if (comando_field) {
            std::string comando = comando_field->getSFString();

            if (comando != ultimo_comando) {
                ultimo_comando = comando;

                int nuevo_modo = 0;
                int postura = 0;
                double inicio = 0.0;
                char orden[16] = "";

                if (std::sscanf(comando.c_str(), "M%d %15s", &nuevo_modo, orden) >= 1) {
                    modo = nuevo_modo;
                }

                if (std::sscanf(comando.c_str(), "M%*d POSE %d %lf", &postura, &inicio) == 2) {
                    postura_activa = postura;
                    inicio_patron = inicio;
                } else {
                    // "IDLE", "TRACK" o vacio: se cancela el patron
                    postura_activa = 0;
                }
            }
        }

        double theta_1 = 0.0;
        double theta_2 = 0.0;

        // Direccion del panel desde el centro, en la imagen cenital:
        // derecha (u) = -Y del mundo, arriba (v) = +X del mundo
        double dir_u = -(my_pos[1] - CENTRO_Y);
        double dir_v = my_pos[0] - CENTRO_X;

        patrones::Punto punto;
        bool en_patron = postura_activa != 0 &&
            patrones::patron(postura_activa, robot->getTime() - inicio_patron,
                             dir_u, dir_v, en_borde, punto);

        if (en_patron) {
            // Patron de la postura: u -> gdl1, v -> gdl2
            theta_1 = punto.u;
            theta_2 = punto.v;

        } else if (modo != MODO_TRACKING) {
            // JUEGO / TEST: se ignora la esfera, el panel queda en 0,0
            postura_activa = 0;
            theta_1 = 0.0;
            theta_2 = 0.0;

        } else {
            postura_activa = 0;

            // 1) Leer la posicion REAL de la esfera (la reporta la Camara)
            double target_x = 0.0, target_y = 0.0, target_z = 0.25;
            if (trans_field) {
                const double *pos = trans_field->getSFVec3f();
                target_x = pos[0];
                target_y = pos[1];
                target_z = pos[2];
            }

            // 2) Vector unitario de este panel hacia la esfera
            double v_x = target_x - my_pos[0];
            double v_y = target_y - my_pos[1];
            double v_z = target_z - (my_pos[2] + 0.025); // offset al pivote del motor

            double mag = std::sqrt(v_x * v_x + v_y * v_y + v_z * v_z);
            if (mag > 0.0) { v_x /= mag; v_y /= mag; v_z /= mag; }

            // 3) Cinematica inversa: vector -> angulos de los 2 ejes
            theta_1 = std::atan2(-v_y, v_z);
            theta_2 = std::asin(std::max(-1.0, std::min(1.0, v_x)));
        }

        // Limitar a los topes mecanicos con margen (evita choque de restricciones fisicas)
        theta_1 = std::max(-LIMITE_SEGURO, std::min(LIMITE_SEGURO, theta_1));
        theta_2 = std::max(-LIMITE_SEGURO, std::min(LIMITE_SEGURO, theta_2));

        // 4) Suavizado proporcional: avanza una fraccion del error, con tope por paso
        double d1 = std::max(-MAX_PASO, std::min(MAX_PASO, (theta_1 - theta_1_actual) * K_SUAVIZADO));
        double d2 = std::max(-MAX_PASO, std::min(MAX_PASO, (theta_2 - theta_2_actual) * K_SUAVIZADO));
        theta_1_actual += d1;
        theta_2_actual += d2;

        // 5) Aplicar a los motores
        if (motor_gdl1 && motor_gdl2) {
            motor_gdl1->setPosition(theta_1_actual);
            motor_gdl2->setPosition(theta_2_actual);
        }
    }

    delete robot;
    return 0;
}
