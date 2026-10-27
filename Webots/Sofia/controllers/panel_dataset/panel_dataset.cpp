// =============================================
// PANEL PARA EL DATASET - SOFIA (diagnostico de alineacion)
// =============================================
//
// Se usa en sofia_dataset.wbt y sofia_diagnostico_vivo.wbt (PROTO sofia).
// Pone la unidad en el angulo exacto que pide el supervisor y reporta lo
// que miden sus sensores:
//     theta_1 -> joint_1            (sensor joint_1_sensor)
//     theta_2 -> joint_3 y joint_2  (joint_2 es la biela; sensor joint_3_sensor)
//
// El generador (DEF GENERADOR) escribe en su customData:
//
//     "S <muestra> <t1_0> <t2_0> <t1_1> <t2_1> ... <t1_15> <t2_15>"
//
// con los angulos de los 16 paneles en radianes (indice = fila*4 + columna).
//
// Este panel escribe en SU customData:
//
//     "P <muestra> <medido_1> <medido_2> <listo>"
//
// listo = 1 cuando los dos ejes llevan varios pasos quietos en el
// objetivo; entonces el generador toma la foto.

#include <webots/Supervisor.hpp>
#include <webots/Motor.hpp>
#include <webots/PositionSensor.hpp>
#include <webots/Node.hpp>
#include <webots/Field.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>

using namespace webots;

const double LIMITE_SEGURO = 0.48;      // rad (27.5 grados)
const double TOLERANCIA = 0.0015;       // rad (~0.09 grados)
const int PASOS_QUIETO = 5;             // pasos seguidos dentro de la tolerancia

int main() {
    Supervisor *robot = new Supervisor();
    int timeStep = (int)robot->getBasicTimeStep();

    Motor *motor_1 = robot->getMotor("joint_1");
    Motor *motor_2 = robot->getMotor("joint_3");          // lleva la placa
    Motor *motor_biela = robot->getMotor("joint_2");      // biela: mismo angulo que joint_3
    PositionSensor *sensor_1 = robot->getPositionSensor("joint_1_sensor");
    PositionSensor *sensor_2 = robot->getPositionSensor("joint_3_sensor");

    if (!motor_1 || !motor_2 || !motor_biela || !sensor_1 || !sensor_2) {
        std::cerr << "[" << robot->getName() << "] ERROR: faltan motores o sensores." << std::endl;
        delete robot;
        return 1;
    }

    sensor_1->enable(timeStep);
    sensor_2->enable(timeStep);

    Node *generador = robot->getFromDef("GENERADOR");
    Field *orden_field = generador ? generador->getField("customData") : nullptr;
    if (!orden_field) {
        std::cerr << "[" << robot->getName() << "] ERROR: no se encontro DEF GENERADOR." << std::endl;
    }

    // Indice del panel a partir de su nombre "Panel_<fila>_<columna>"
    int fila = -1, columna = -1;
    std::sscanf(robot->getName().c_str(), "Panel_%d_%d", &fila, &columna);
    const int indice = fila * 4 + columna;

    std::string ultima_orden;
    int muestra = -1;
    double objetivo_1 = 0.0, objetivo_2 = 0.0;
    int pasos_quieto = 0;

    while (robot->step(timeStep) != -1) {

        // 1) Nueva orden del generador?
        if (orden_field) {
            std::string orden = orden_field->getSFString();

            if (orden != ultima_orden) {
                ultima_orden = orden;

                std::istringstream lectura(orden);
                std::string tipo;
                int nueva_muestra;
                lectura >> tipo >> nueva_muestra;

                if (tipo == "S" && lectura) {
                    double angulos[32];
                    int leidos = 0;
                    while (leidos < 32 && (lectura >> angulos[leidos])) {
                        leidos++;
                    }

                    if (leidos == 32 && indice >= 0 && indice < 16) {
                        muestra = nueva_muestra;
                        objetivo_1 = std::max(-LIMITE_SEGURO, std::min(LIMITE_SEGURO, angulos[2 * indice]));
                        objetivo_2 = std::max(-LIMITE_SEGURO, std::min(LIMITE_SEGURO, angulos[2 * indice + 1]));
                        pasos_quieto = 0;
                    }
                }
            }
        }

        // 2) Ir al objetivo
        motor_1->setPosition(objetivo_1);
        motor_2->setPosition(objetivo_2);
        motor_biela->setPosition(objetivo_2);

        // 3) Medir y avisar cuando ya llego
        double medido_1 = sensor_1->getValue();
        double medido_2 = sensor_2->getValue();

        bool en_objetivo = std::fabs(medido_1 - objetivo_1) < TOLERANCIA &&
                           std::fabs(medido_2 - objetivo_2) < TOLERANCIA;
        pasos_quieto = en_objetivo ? pasos_quieto + 1 : 0;

        char reporte[96];
        std::snprintf(reporte, sizeof(reporte), "P %d %.6f %.6f %d",
                      muestra, medido_1, medido_2, pasos_quieto >= PASOS_QUIETO ? 1 : 0);
        robot->setCustomData(reporte);
    }

    delete robot;
    return 0;
}
