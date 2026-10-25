#include <webots/Supervisor.hpp>
#include <cmath>

using namespace webots;

// Controlador de la esfera: se mueve a si misma, de forma autonoma.
// La trayectoria esta centrada en el punto imaginario (0,0) del arreglo.
// Ningun panel la controla; los paneles solo leen esta posicion.
int main(int argc, char **argv) {
    Supervisor *robot = new Supervisor();
    int timeStep = (int)robot->getBasicTimeStep();

    // Campo de traslacion de este mismo Robot (la esfera)
    Field *trans_field = robot->getSelf()->getField("translation");

    const double VELOCIDAD_ESFERA = 0.5; // < 1 = mas lenta, > 1 = mas rapida
    double t = 0.0;

    while (robot->step(timeStep) != -1) {
        // Trayectoria relativa al origen (0,0) del arreglo
        double tt = t * VELOCIDAD_ESFERA;
        double x = 0.3 * std::sin(tt * 1.5);
        double y = 0.3 * std::sin(tt * 2.0);
        double z = 0.25 + 0.05 * std::cos(tt * 2.0);

        double pos[3] = {x, y, z};
        trans_field->setSFVec3f(pos);

        t += (double)timeStep / 1000.0;
    }

    delete robot;
    return 0;
}