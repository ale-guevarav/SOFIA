/*
 * =============================================================
 *  SOFIA - MOVIMIENTO DEL MÓDULO (16 UNIDADES, 2 PCA9685)
 * =============================================================
 *
 *  El módulo tiene 16 unidades de 2 servos (32 servos) en dos
 *  PCA9685 del mismo bus I2C, 8 unidades por placa:
 *
 *      placa 1 (dirección menor)  -> unidades 1-8
 *      placa 2                    -> unidades 9-16
 *      en cada placa: canal 0 = X y 1 = Y de su primera unidad,
 *                     canal 2 = X y 3 = Y de la segunda, etc.
 *
 *  Las figuras las forma EL MÓDULO COMPLETO, como el círculo de carga:
 *  cada figura tiene un GRUPO FIJO de unidades (las que quedan sobre
 *  la figura) y una "esfera" virtual recorre la figura a velocidad
 *  constante. Las unidades del grupo SIGUEN a la esfera, igual que en
 *  el tracking: se inclinan hacia ella, así que el movimiento es
 *  continuo y suave. Solo se mueven las SIMULTANEAS (3) unidades del
 *  grupo más cercanas a la esfera; las demás esperan en el centro.
 *
 *      1 INICIO    -> arriba-abajo por el centro del módulo
 *      2 RECARGAR  -> círculo de carga, como siempre: una cabeza gira
 *                     por el borde en sentido horario (2 vueltas) y las
 *                     unidades del borde se inclinan hacia afuera con
 *                     una cola que se apaga (máximo SIMULTANEAS)
 *      3 ESCUDO    -> rombo
 *      4 ATAQUE    -> una L
 *      5 FIN       -> izquierda-derecha (despedida)
 *      6 GANA      -> zigzag que sube por todo el módulo (Vaquerito: gana el robot)
 *      7 PIERDE    -> zigzag que cae y se va cerrando (Vaquerito: pierde el robot)
 *
 *  El servo X inclina hacia la derecha de la cámara y el Y hacia
 *  arriba. Unidad 1 = abajo a la izquierda, 16 = arriba a la derecha.
 *  Las mismas figuras están en la sim (patrones.hpp).
 *
 *  En modo TRACKING las 16 apuntan hacia la mano POR TURNOS, como el
 *  reloj de un CPU: cada 20 ms solo 4 unidades dan un salto corto y
 *  ceden el turno a las siguientes 4. Avanzan casi juntas pero nunca
 *  arrancan más de 8 servos a la vez. El regreso al centro (STOP,
 *  estado seguro, fin del TRACKING) usa los mismos turnos.
 *
 *  Hardware y calibración tomados de las pruebas de
 *  mecatrónica (Prueba_Servos / SG90_WindowVelocity_PCA).
 * =============================================================
 */

#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <math.h>

// =============================================
// HARDWARE (igual que las pruebas de mecatrónica)
// =============================================

// ESP32-C3 SuperMini + 2 PCA9685 en el mismo bus I2C.
// Pines según la PCB de SOFIA (PCB/SOFIA_PCB en main):
//   GPIO 0 = SDA, GPIO 1 = SCL, GPIO 3 = OE (conectores J1 y J2)
//   GPIO 5 y 6 = RX/TX del MAX485 (no se usan aquí: no tocarlos)
const int SDA_PIN = 0;
const int SCL_PIN = 1;
const int OE_PIN  = 5;     // LOW = salidas de los PCA9685 habilitadas

// 100 kHz, igual que las pruebas de mecatrónica (lo más seguro con
// cables largos entre placas). Como solo se escriben las unidades que
// se mueven (~3), alcanza de sobra dentro de los 20 ms del periodo
const uint32_t I2C_HZ = 100000;

// Direcciones si no se pueden detectar solas. Al arrancar se
// buscan los PCA9685 en el bus y se usan en orden de dirección
// (la segunda placa debe tener puenteado A0 u otro jumper)
const int NUM_PLACAS = 2;
const uint8_t PCA_DIRECCIONES_DEFAULT[NUM_PLACAS] = {0x40, 0x41};

const int UNIDADES_POR_PLACA = 8;
const int NUM_UNIDADES = NUM_PLACAS * UNIDADES_POR_PLACA;   // 16

// Canales de la unidad k (0-7) dentro de su placa
inline int canalX(int k) { return 2 * k; }       // Horizontal
inline int canalY(int k) { return 2 * k + 1; }   // Vertical

// =============================================
// CALIBRACIÓN (de SG90_WindowVelocity_PCA)
// =============================================

const float THETA_MIN = -60.0f;   // grados
const float THETA_MAX =  60.0f;

const int PWM_EN_THETA_MIN = 385;   // cuentas del PCA9685 en -60°
const int PWM_EN_THETA_MAX = 225;   // cuentas del PCA9685 en +60°

// Si un eje se mueve al revés de lo esperado,
// cambiar a true (no hace falta tocar nada más)
const bool INVERTIR_X = false;
const bool INVERTIR_Y = false;

// Ajuste fino por unidad (grados que se suman a su centro), por si
// alguna placa no queda plana en 0°. Unidad 1 = posición 0
const float AJUSTE_X[NUM_UNIDADES] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
const float AJUSTE_Y[NUM_UNIDADES] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

// Al arrancar se centran las unidades de una en una con esta pausa,
// para no pedir la corriente de los 32 servos al mismo tiempo
const int PAUSA_ARRANQUE_MS = 1000;

// =============================================
// PARÁMETROS DE MOVIMIENTO
// =============================================

// Periodo de control: 20 ms (igual que las pruebas)
const unsigned long TS_US = 20000UL;
const float TS_S = 0.020f;

// Tamaño de los patrones: grados desde el centro.
// 20° porque las unidades se mueven desfasadas: dos vecinas pueden
// inclinarse una hacia la otra. Con 134 mm entre centros (30 mm entre
// aristas) a ±20° por eje quedan ~6 mm entre placas; a ±25° solo
// ~1.5 mm y a ±30° se tocan
const float AMPLITUD = 20.0f;

// FIGURAS DEL MÓDULO (las mismas que la sim, patrones.hpp)
// Cuántas unidades se mueven a la vez en una figura (las más cercanas
// a la esfera)
const int SIMULTANEAS = 3;

struct Punto {
  float x;
  float y;
};

// Camino de la esfera en cada figura, de -1 a 1 (1 = borde del
// arreglo): x = derecha de la cámara, y = arriba
const Punto FIG_INICIO[] = {{0, 0}, {0, 1}, {0, -1}, {0, 0}};                 // arriba-abajo
const Punto FIG_ESCUDO[] = {{0, 1}, {1, 0}, {0, -1}, {-1, 0}, {0, 1}};        // rombo
const Punto FIG_ATAQUE[] = {{-0.5f, 1}, {-0.5f, -1}, {0.8f, -1}};             // L
const Punto FIG_FIN[] = {{-1, 0}, {1, 0}, {-1, 0}, {1, 0}};                   // izq-der
// Reacciones del robot al final de una partida de Vaquerito (las manda la PC)
const Punto FIG_GANA[] = {{-1, -1}, {-0.6f, 1}, {-0.2f, -1}, {0.2f, 1}, {0.6f, -1}, {1, 1}};   // zigzag que sube (festejo)
const Punto FIG_PIERDE[] = {{-1, 1}, {1, 0.5f}, {-0.6f, 0}, {0.6f, -0.5f}, {0, -1}};          // zigzag que cae y se cierra

// Medio ancho y medio alto del arreglo (mm): tamaño de la figura
const float TAM_FIGURA_X = 234.5f;
const float TAM_FIGURA_Y = 174.1f;

// Velocidad de la esfera en cada figura (mm/s)
//                            -  INICIO  RECARGAR  ESCUDO  ATAQUE  FIN  GANA  PIERDE
const float VEL_ESFERA[8] = {0, 350,    0,        550,    360,    470, 600,  300};

// GRUPO FIJO de cada figura: las unidades que quedan a menos de ~85 mm
// del camino (1 = abajo a la izquierda, 16 = arriba a la derecha).
// Se pueden quitar o agregar unidades aquí
//
//        13  14  15  16      fila de arriba
//      9  10  11  12
//        5   6   7   8
//      1   2   3   4         fila de abajo
//
const uint8_t GRUPO_INICIO[] = {3, 6, 11, 14};
const uint8_t GRUPO_ESCUDO[] = {2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15};
const uint8_t GRUPO_ATAQUE[] = {2, 3, 4, 5, 6, 10, 13, 14};
const uint8_t GRUPO_FIN[] = {5, 6, 7, 8, 9, 10, 11, 12};
const uint8_t GRUPO_GANA[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
const uint8_t GRUPO_PIERDE[] = {3, 5, 6, 7, 10, 11, 12, 13, 14, 15};

// Cómo sigue cada unidad a la esfera:
//  - se inclina HACIA la esfera; con la esfera encima queda plana y la
//    sigue cuando pasa (como en el tracking)
//  - a menos de DIST_LLENA de la esfera se inclina completa (±20°)
//  - se apaga poco a poco entre RADIO_LLENO y RADIO_ESFERA
const float DIST_LLENA   = 70.0f;    // mm
const float RADIO_LLENO  = 100.0f;   // mm
const float RADIO_ESFERA = 200.0f;   // mm
// Relevo: cuando la unidad que va a entrar queda a menos de esto de una
// de las 3 que se mueven, la de adentro empieza a apagarse
const float RELEVO_MM    = 70.0f;    // mm

// RECARGAR ("círculo de carga"), como en la sim original
const float RECARGA_VUELTA_S = 1.2f;   // segundos por vuelta
const int   RECARGA_VUELTAS  = 2;
const float RECARGA_COLA     = 2.2f;   // rad de "cola" encendida detrás de la cabeza

// Suavizado de la sim (K = 0.15 cada 8 ms) pasado a pasos de 20 ms
const float K_SUAVIZADO = 0.33f;

// SUAVIZADOR: cómo llega cada unidad a su inclinación (se cambia en
// vivo con 's' en el Monitor Serie, para probar cuál se ve mejor):
//   S_EMA     avanza el 33 % de lo que le falta cada 20 ms (como la sim)
//   S_SIN     salta directo; el servo va a toda su velocidad
//   S_FRENA   arranca de golpe (ACELERACION alta) y frena justo antes
//             de llegar o de cambiar de dirección
//   S_SUAVE   2º orden críticamente amortiguado: arranca y frena sin
//             tirones, sin pasarse
enum Suavizador { S_EMA, S_SIN, S_FRENA, S_SUAVE, NUM_SUAVIZADORES };
const char* NOMBRES_SUAVIZADOR[] = {
  "EMA (como la sim)", "SIN SUAVIZADO", "ARRANCA DE GOLPE Y FRENA AL LLEGAR", "SUAVE (2o orden)"
};
int suavizador = S_EMA;

const float ACELERACION  = 4000.0f;   // S_FRENA: °/s² (llega a 300 °/s en 0.075 s)
const float VEL_UNIDAD   = 300.0f;    // S_FRENA: °/s máximo
const float OMEGA_SUAVE  = 30.0f;     // S_SUAVE: rad/s (llega en ~0.15 s)

// Multiplica la velocidad de las figuras (se cambia en vivo con '+' y
// '-'): 2.0 = la cabeza pasa el doble de rápido. Aplica desde la
// siguiente figura
float escalaVelocidad = 1.0f;

const float VEL_REGRESO = 120.0f;   // °/s al volver al centro si se interrumpe
const float VEL_TRACK   = 120.0f;   // °/s promedio de cada unidad en TRACKING

// TRACKING POR TURNOS (como el reloj de un CPU): en cada paso de 20 ms
// solo se mueven TRACK_POR_TURNO unidades, dan un salto corto hacia la
// mano y le ceden el turno a las siguientes 4. Así las 16 avanzan casi
// juntas pero nunca hay más de 4 unidades (8 servos) arrancando a la vez.
// El salto se calcula para que el promedio sea VEL_TRACK; con 16
// unidades: 120 °/s x 0.02 s x 4 turnos = 9.6° por salto, cada 80 ms
const int   TRACK_POR_TURNO = 4;
// Tope del salto: un SG90 recorre ~10° en los 20 ms de su turno, así
// termina su salto antes de que le toque a las siguientes
const float TRACK_SALTO_MAX = 10.0f;

// Dónde está cada unidad en el módulo, VISTO DESDE LA CÁMARA:
// fila 0 = abajo, columna 0 = izquierda. Por defecto la unidad 1 está
// abajo a la izquierda y la 16 arriba a la derecha (placa 1 = las dos
// filas de abajo). Si el cableado es otro, cámbialo aquí
//                                    unidad: 1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
const uint8_t FILA_UNIDAD[NUM_UNIDADES]    = {0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3};
const uint8_t COLUMNA_UNIDAD[NUM_UNIDADES] = {0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3};

// TRACKING: grados de giro cuando la mano está
// en el borde de la imagen (x_norm o y_norm = ±1)
const float RANGO_TRACK = 45.0f;

// Sentido del TRACKING. La imagen de la PC llega en espejo (como selfie):
// x_norm > 0 = mano a la derecha de la persona. En el módulo real las
// unidades se iban al lado contrario, así que se invierte X (solo en el
// TRACKING; las figuras no cambian). Si arriba/abajo también sale al
// revés, pon TRACK_INVERTIR_Y en true
const bool TRACK_INVERTIR_X = true;
const bool TRACK_INVERTIR_Y = false;

// Si en TRACKING no llega posición en este tiempo,
// las unidades regresan al centro
const unsigned long TRACK_TIMEOUT_MS = 3000UL;

// No se reenvía al PCA9685 si el cambio es menor a esto
const float E_QUANT = 0.10f;

// =============================================
// TIPOS Y ESTADO
// =============================================

// Estado general del módulo
enum EstadoMovimiento {
  QUIETO,
  PATRON,
  SIGUIENDO_MANO,
  REGRESANDO,
  PRUEBA,           // movimiento de prueba de una unidad (teclas u / e / p)
};

// Estado de cada unidad
enum FaseUnidad : uint8_t {
  U_QUIETA,     // en el centro, sin moverse
  U_FIGURA,     // dibujando la figura
  U_REGRESO,    // volviendo al centro
  U_MANO,       // siguiendo la mano (TRACKING)
  U_PRUEBA,     // haciendo el movimiento de prueba
};

struct Unidad {
  float x, y;                 // posición actual (grados)
  float enviadoX, enviadoY;   // última enviada al PCA9685
  float vx, vy;               // velocidad (°/s), para S_FRENA y S_SUAVE
  FaseUnidad fase;
};

const char* NOMBRES_PATRON[] = {
  "CENTRO", "ARRIBA-ABAJO", "CIRCULO DE CARGA", "ROMBO", "L", "IZQUIERDA-DERECHA",
  "ZIGZAG QUE SUBE (GANA)", "ZIGZAG QUE CAE (PIERDE)"
};

Adafruit_PWMServoDriver* placas[NUM_PLACAS] = {nullptr, nullptr};
uint8_t direccionPlaca[NUM_PLACAS] = {0, 0};
int placasEncontradas = 0;

// Prueba de cableado: -1 = todas las unidades;
// 0-15 = unidad elegida con 'u' (solo esa participa en las figuras)
int unidadPrueba = -1;

// MOVIMIENTO DE PRUEBA (teclas u / e / p): la unidad elegida va a cada
// punto, espera un momento y sigue, en ciclo, hasta que se pausa
const float VEL_PRUEBA = 60.0f;                 // °/s
const unsigned long PAUSA_PRUEBA_MS = 300UL;    // espera en cada punto
const float DIAG = 0.7071f;                     // en diagonal, ±20° en total
struct PuntoPrueba { float x, y; const char* nombre; };
const PuntoPrueba PASOS_PRUEBA[] = {
  {0, 1, "arriba"}, {0, -1, "abajo"}, {0, 0, "centro"},
  {-1, 0, "izquierda"}, {1, 0, "derecha"}, {0, 0, "centro"},
  {DIAG, DIAG, "diagonal arriba-derecha"}, {-DIAG, -DIAG, "diagonal abajo-izquierda"}, {0, 0, "centro"},
  {-DIAG, DIAG, "diagonal arriba-izquierda"}, {DIAG, -DIAG, "diagonal abajo-derecha"}, {0, 0, "centro"},
};
const int NUM_PASOS_PRUEBA = sizeof(PASOS_PRUEBA) / sizeof(PASOS_PRUEBA[0]);
int pasoPrueba = 0;
unsigned long llegoPruebaMs = 0;   // 0 = va en camino al punto

EstadoMovimiento estado = QUIETO;
Unidad unidades[NUM_UNIDADES];

// Figura actual
int patronActual = 0;
unsigned long inicioPatronMs = 0;
float escalaPatron = 1.0f;  // escalaVelocidad al empezar la figura

// Objetivo en TRACKING
Punto objetivoMano = {0.0f, 0.0f};
unsigned long ultimoTrackMs = 0;

unsigned long tControlUs = 0;

// =============================================
// SERVOS
// =============================================

float saturar(float x, float xmin, float xmax) {
  if (x < xmin) return xmin;
  if (x > xmax) return xmax;
  return x;
}

int theta_a_pwm(float theta) {
  theta = saturar(theta, THETA_MIN, THETA_MAX);

  float m = (float)(PWM_EN_THETA_MAX - PWM_EN_THETA_MIN) / (THETA_MAX - THETA_MIN);

  return (int)roundf(PWM_EN_THETA_MIN + m * (theta - THETA_MIN));
}

// Escribe los 2 canales de una unidad con setPWM de la librería
// (lo mismo que usaban las pruebas de mecatrónica)
void escribirUnidad(int u) {
  int b = u / UNIDADES_POR_PLACA;
  int k = u % UNIDADES_POR_PLACA;

  if (b >= placasEncontradas) return;

  Unidad& un = unidades[u];
  float thetaX = (INVERTIR_X ? -un.x : un.x) + AJUSTE_X[u];
  float thetaY = (INVERTIR_Y ? -un.y : un.y) + AJUSTE_Y[u];
  int cuentas[2] = {theta_a_pwm(thetaX), theta_a_pwm(thetaY)};

  placas[b]->setPWM(canalX(k), 0, cuentas[0]);
  placas[b]->setPWM(canalY(k), 0, cuentas[1]);

  un.enviadoX = un.x;
  un.enviadoY = un.y;
}

// Solo viajan por I2C las unidades cuya posición cambió
void aplicarServos(bool forzar = false) {
  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];
    if (forzar ||
        fabsf(un.x - un.enviadoX) >= E_QUANT ||
        fabsf(un.y - un.enviadoY) >= E_QUANT) {
      escribirUnidad(u);
    }
  }
}

// Busca PCA9685 en el bus (0x40-0x7F; 0x70 es la dirección
// "todas las placas" y se salta). Regresa cuántas encontró
int buscarPlacas(uint8_t encontradas[], int maximo) {
  int n = 0;
  for (uint8_t dir = 0x40; dir <= 0x7F && n < maximo; dir++) {
    if (dir == 0x70) continue;
    Wire.beginTransmission(dir);
    if (Wire.endTransmission() == 0) {
      encontradas[n++] = dir;
    }
  }
  return n;
}

bool iniciarServos() {
  // Mismo orden que las pruebas de mecatrónica
  pinMode(OE_PIN, OUTPUT);
  digitalWrite(OE_PIN, LOW);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(I2C_HZ);

  for (int u = 0; u < NUM_UNIDADES; u++) {
    unidades[u] = {0.0f, 0.0f, -1000.0f, -1000.0f, 0.0f, 0.0f, U_QUIETA};
  }

  uint8_t encontradas[NUM_PLACAS];
  int n = buscarPlacas(encontradas, NUM_PLACAS);

  if (n == 0) {
    // Nada respondió: intentar con las direcciones por defecto
    for (int b = 0; b < NUM_PLACAS; b++) encontradas[b] = PCA_DIRECCIONES_DEFAULT[b];
    n = NUM_PLACAS;
  }

  placasEncontradas = 0;

  for (int b = 0; b < n; b++) {
    Adafruit_PWMServoDriver* placa = new Adafruit_PWMServoDriver(encontradas[b]);

    if (!placa->begin()) {
      Serial.printf("PCA9685 en 0x%02X: no responde\n", encontradas[b]);
      delete placa;
      continue;
    }

    placa->setOscillatorFrequency(27000000);
    placa->setPWMFreq(50);

    placas[placasEncontradas] = placa;
    direccionPlaca[placasEncontradas] = encontradas[b];
    placasEncontradas++;

    int primera = (placasEncontradas - 1) * UNIDADES_POR_PLACA + 1;
    Serial.printf("PCA9685 en 0x%02X -> unidades %d-%d\n",
                  encontradas[b], primera, primera + UNIDADES_POR_PLACA - 1);
  }

  if (placasEncontradas == 0) {
    return false;
  }

  if (placasEncontradas < NUM_PLACAS) {
    Serial.printf("AVISO: solo %d de %d PCA9685; se mueven %d unidades\n",
                  placasEncontradas, NUM_PLACAS, placasEncontradas * UNIDADES_POR_PLACA);
  }

  delay(300);

  // Centrar de una en una (evita el pico de corriente de 32 servos)
  for (int u = 0; u < placasEncontradas * UNIDADES_POR_PLACA; u++) {
    escribirUnidad(u);
    delay(PAUSA_ARRANQUE_MS);
  }

  tControlUs = micros();
  return true;
}

// =============================================
// FIGURAS DEL MÓDULO
// =============================================

// Dirección de la unidad vista desde el centro del módulo, en la
// imagen de la cámara (u = derecha, v = arriba). Mismas posiciones
// que los paneles de sofia.wbt
void direccionUnidad(int u, float& du, float& dv) {
  const float FILAS_X[4] = {-0.1741f, -0.0580f, 0.0580f, 0.1741f};
  // Como el módulo real: 134 mm entre centros y las filas 2 y 4
  // (unidades 5-8 y 13-16) corridas 67 mm a la derecha
  int f = FILA_UNIDAD[u], c = COLUMNA_UNIDAD[u];
  du = -0.2345f + 0.067f * (f % 2) + 0.134f * c;
  dv = FILAS_X[f];
}

bool enBorde(int u) {
  int f = FILA_UNIDAD[u], c = COLUMNA_UNIDAD[u];
  return f == 0 || f == 3 || c == 0 || c == 3;
}

#define N_ARR(a) ((int)(sizeof(a) / sizeof(a[0])))

void figuraDe(int pose, const Punto*& fig, int& n, const uint8_t*& grupo, int& ng) {
  switch (pose) {
    case 1: fig = FIG_INICIO; n = N_ARR(FIG_INICIO); grupo = GRUPO_INICIO; ng = N_ARR(GRUPO_INICIO); break;
    case 3: fig = FIG_ESCUDO; n = N_ARR(FIG_ESCUDO); grupo = GRUPO_ESCUDO; ng = N_ARR(GRUPO_ESCUDO); break;
    case 4: fig = FIG_ATAQUE; n = N_ARR(FIG_ATAQUE); grupo = GRUPO_ATAQUE; ng = N_ARR(GRUPO_ATAQUE); break;
    case 5: fig = FIG_FIN;    n = N_ARR(FIG_FIN);    grupo = GRUPO_FIN;    ng = N_ARR(GRUPO_FIN);    break;
    case 6: fig = FIG_GANA;   n = N_ARR(FIG_GANA);   grupo = GRUPO_GANA;   ng = N_ARR(GRUPO_GANA);   break;
    case 7: fig = FIG_PIERDE; n = N_ARR(FIG_PIERDE); grupo = GRUPO_PIERDE; ng = N_ARR(GRUPO_PIERDE); break;
    default: fig = nullptr; n = 0; grupo = nullptr; ng = 0; break;
  }
}

// Dónde va la esfera (mm) a los t segundos. Regresa false si ya acabó
bool posicionEsfera(int pose, float t, float& ex, float& ey) {
  const Punto* fig; const uint8_t* grupo; int n, ng;
  figuraDe(pose, fig, n, grupo, ng);
  if (n == 0) return false;
  float recorrido = VEL_ESFERA[pose] * escalaPatron * t;
  for (int i = 1; i < n; i++) {
    float ax = fig[i - 1].x * TAM_FIGURA_X, ay = fig[i - 1].y * TAM_FIGURA_Y;
    float bx = fig[i].x * TAM_FIGURA_X,     by = fig[i].y * TAM_FIGURA_Y;
    float tramo = hypotf(bx - ax, by - ay);
    if (recorrido <= tramo) {
      float f = tramo > 0.0f ? recorrido / tramo : 1.0f;
      ex = ax + f * (bx - ax);
      ey = ay + f * (by - ay);
      return true;
    }
    recorrido -= tramo;
  }
  return false;
}

bool enGrupo(int u, const uint8_t* grupo, int ng) {
  for (int k = 0; k < ng; k++) if (grupo[k] == u + 1) return true;
  return false;
}

// Distancia (mm) de la unidad u a la esfera
float distanciaEsfera(int u, float ex, float ey) {
  float du, dv;
  direccionUnidad(u, du, dv);
  return hypotf(ex - du * 1000.0f, ey - dv * 1000.0f);
}

// RECARGAR: qué tanto se inclina la unidad u (0-1) a los t segundos.
// Una cabeza gira por el borde en sentido horario y deja una cola
// que se apaga (igual que la sim original)
float intensidadRecarga(int u, float t) {
  if (!enBorde(u)) return 0.0f;
  float du, dv;
  direccionUnidad(u, du, dv);
  float anguloUnidad = atan2f(dv, du);
  float cabeza = -2.0f * PI * t / RECARGA_VUELTA_S;   // sentido horario
  float atras = fmodf(anguloUnidad - cabeza, 2.0f * PI);
  if (atras < 0.0f) atras += 2.0f * PI;
  // La cola se acorta para que quepan SIMULTANEAS unidades del borde
  // (12 unidades = una cada 2π/12 rad) y la última se apague antes de
  // que entre la siguiente
  float cola = (SIMULTANEAS - 0.5f) * 2.0f * PI / 12.0f;
  if (cola > RECARGA_COLA) cola = RECARGA_COLA;
  return atras < cola ? 1.0f - atras / cola : 0.0f;
}

bool objetivoRecarga(int u, float t, float& x, float& y) {
  if (t > RECARGA_VUELTA_S * RECARGA_VUELTAS) return false;

  float mia = intensidadRecarga(u, t);
  if (mia <= 0.0f) return true;

  // La cola alcanza a ~4 unidades: solo se mueven las SIMULTANEAS más
  // inclinadas (las más cercanas a la cabeza); la del final de la cola
  // se queda en el centro
  int masInclinadas = 0;
  for (int k = 0; k < placasEncontradas * UNIDADES_POR_PLACA; k++) {
    if (k == u) continue;
    float otra = intensidadRecarga(k, t);
    if (otra > mia || (otra == mia && k < u)) masInclinadas++;
  }
  if (masInclinadas >= SIMULTANEAS) return true;

  // Inclinarse hacia afuera del módulo
  float du, dv;
  direccionUnidad(u, du, dv);
  float norma = hypotf(du, dv);
  x = AMPLITUD * mia * du / norma;
  y = AMPLITUD * mia * dv / norma;
  return true;
}

// Inclinación que le toca a la unidad u a los t segundos de la figura.
// Regresa false cuando la figura ya terminó
bool objetivoFigura(int pose, int u, float t, float& x, float& y) {
  x = 0.0f;
  y = 0.0f;

  if (pose == 2) return objetivoRecarga(u, t * escalaPatron, x, y);

  // Figura con esfera: solo el grupo fijo, y de él las SIMULTANEAS
  // unidades más cercanas a la esfera
  const Punto* fig; const uint8_t* grupo; int n, ng;
  figuraDe(pose, fig, n, grupo, ng);
  if (n == 0) return false;

  float ex, ey;
  if (!posicionEsfera(pose, t, ex, ey)) return false;
  if (!enGrupo(u, grupo, ng)) return true;

  float d = distanciaEsfera(u, ex, ey);
  int masCercanas = 0;
  // Distancia de la primera unidad que se queda FUERA (la número
  // SIMULTANEAS + 1 más cercana). Entre más se le acerca una unidad de
  // las de adentro, menos se inclina: así el relevo entre la que sale y
  // la que entra es suave y nunca brinca
  float fuera[SIMULTANEAS + 1];
  int nf = 0;
  for (int k = 0; k < ng; k++) {
    int otra = grupo[k] - 1;
    if (otra == u || otra >= placasEncontradas * UNIDADES_POR_PLACA) continue;
    float dOtra = distanciaEsfera(otra, ex, ey);
    if (dOtra < d || (dOtra == d && otra < u)) masCercanas++;
    // guardar las SIMULTANEAS + 1 distancias más chicas (ordenadas)
    int j;
    if (nf < SIMULTANEAS + 1) {
      j = nf++;
    } else {
      if (dOtra >= fuera[SIMULTANEAS]) continue;
      j = SIMULTANEAS;
    }
    while (j > 0 && fuera[j - 1] > dOtra) { fuera[j] = fuera[j - 1]; j--; }
    fuera[j] = dOtra;
  }
  if (masCercanas >= SIMULTANEAS) return true;
  // Sin contar a esta unidad, la que queda fuera es la SIMULTANEAS-ésima
  // de las otras (índice SIMULTANEAS - 1)
  float relevo = nf >= SIMULTANEAS ? saturar((fuera[SIMULTANEAS - 1] - d) / RELEVO_MM, 0.0f, 1.0f) : 1.0f;

  // Inclinarse HACIA la esfera (como el tracking): completa a partir de
  // DIST_LLENA, proporcional si la esfera está casi encima, y se apaga
  // entre RADIO_LLENO y RADIO_ESFERA
  float du, dv;
  direccionUnidad(u, du, dv);
  float vx = ex - du * 1000.0f, vy = ey - dv * 1000.0f;
  float envolvente = saturar((RADIO_ESFERA - d) / (RADIO_ESFERA - RADIO_LLENO), 0.0f, 1.0f);
  float escala = AMPLITUD * envolvente * relevo / (d > DIST_LLENA ? d : DIST_LLENA);
  x = vx * escala;
  y = vy * escala;
  return true;
}

// Lleva la unidad hacia (tx, ty) con el suavizador elegido
void seguirObjetivo(Unidad& un, float tx, float ty) {
  switch (suavizador) {

    case S_EMA:
      un.x += (tx - un.x) * K_SUAVIZADO;
      un.y += (ty - un.y) * K_SUAVIZADO;
      break;

    case S_SIN:
      un.x = tx;
      un.y = ty;
      break;

    case S_FRENA: {
      // Trapecio: acelera hasta VEL_UNIDAD y frena para llegar justo
      float dx = tx - un.x, dy = ty - un.y, d = hypotf(dx, dy);
      if (d < 0.01f) { un.vx = 0.0f; break; }
      float v = un.vx + ACELERACION * TS_S;
      if (v > VEL_UNIDAD) v = VEL_UNIDAD;
      float vFrenado = sqrtf(2.0f * ACELERACION * d);   // la más rápida que aún frena a tiempo
      if (v > vFrenado) v = vFrenado;
      float paso = v * TS_S;
      if (paso >= d) { un.x = tx; un.y = ty; }
      else { un.x += dx / d * paso; un.y += dy / d * paso; }
      un.vx = v;   // aquí vx guarda la rapidez
      break;
    }

    case S_SUAVE: {
      // Resorte críticamente amortiguado: a = w²(objetivo - x) - 2w v
      un.vx += (OMEGA_SUAVE * OMEGA_SUAVE * (tx - un.x) - 2.0f * OMEGA_SUAVE * un.vx) * TS_S;
      un.vy += (OMEGA_SUAVE * OMEGA_SUAVE * (ty - un.y) - 2.0f * OMEGA_SUAVE * un.vy) * TS_S;
      un.x += un.vx * TS_S;
      un.y += un.vy * TS_S;
      break;
    }
  }
}

// Para probar desde el Monitor Serie
void cambiarSuavizador() {
  suavizador = (suavizador + 1) % NUM_SUAVIZADORES;
  Serial.printf("[MOV] Suavizador: %s\n", NOMBRES_SUAVIZADOR[suavizador]);
}

void cambiarEscalaVelocidad(float factor) {
  escalaVelocidad *= factor;
  if (escalaVelocidad < 0.25f) escalaVelocidad = 0.25f;
  if (escalaVelocidad > 4.0f)  escalaVelocidad = 4.0f;
  Serial.printf("[MOV] Velocidad x%.2f (esfera del ESCUDO a %.0f mm/s; aplica desde la siguiente figura)\n",
                escalaVelocidad, VEL_ESFERA[3] * escalaVelocidad);
}

// =============================================
// COMANDOS DE MOVIMIENTO
// =============================================

// Termina el movimiento de prueba (la unidad regresa al centro)
void detenerPrueba() {
  if (estado != PRUEBA) return;
  for (int u = 0; u < NUM_UNIDADES; u++) {
    if (unidades[u].fase == U_PRUEBA) unidades[u].fase = U_REGRESO;
  }
  estado = REGRESANDO;
}

// Toda unidad fuera del centro (o moviéndose) regresa
void irAlCentro() {
  patronActual = 0;

  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];
    if (un.fase != U_QUIETA || un.x != 0.0f || un.y != 0.0f) {
      un.fase = U_REGRESO;
    }
  }

  estado = REGRESANDO;
}

// pose: 1 INICIO, 2 RECARGAR, 3 ESCUDO, 4 ATAQUE, 5 FIN, 6 GANA, 7 PIERDE
void iniciarPatron(uint8_t pose) {
  if (pose < 1 || pose > 7) {
    irAlCentro();
    return;
  }

  detenerPrueba();
  patronActual = pose;
  estado = PATRON;
  inicioPatronMs = millis();
  escalaPatron = escalaVelocidad;

  // Todas entran a la figura desde donde estén (las que venían de la
  // postura anterior regresan solas cuando la cabeza no les toca).
  // En la prueba de cableado solo entra esa unidad
  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];
    bool participa = u < placasEncontradas * UNIDADES_POR_PLACA &&
                     (unidadPrueba < 0 || u == unidadPrueba);
    if (participa) {
      un.fase = U_FIGURA;
    } else if (un.fase != U_QUIETA) {
      un.fase = U_REGRESO;
    }
  }

  if (pose == 2) {
    Serial.printf("[MOV] Patron: %s (%d vueltas de %.1f s, %d a la vez)\n",
                  NOMBRES_PATRON[pose], RECARGA_VUELTAS, RECARGA_VUELTA_S, SIMULTANEAS);
    return;
  }
  const Punto* fig; const uint8_t* grupo; int n, ng;
  figuraDe(pose, fig, n, grupo, ng);
  float largo = 0.0f;
  for (int i = 1; i < n; i++) {
    largo += hypotf((fig[i].x - fig[i - 1].x) * TAM_FIGURA_X, (fig[i].y - fig[i - 1].y) * TAM_FIGURA_Y);
  }
  Serial.printf("[MOV] Patron: %s (grupo de %d unidades, %d a la vez, ~%.1f s)\n",
                NOMBRES_PATRON[pose], ng, SIMULTANEAS, largo / (VEL_ESFERA[pose] * escalaPatron));
}

// x_norm, y_norm: -1 a 1 (centro de la imagen = 0)
void seguirMano(float xNorm, float yNorm) {
  objetivoMano.x = saturar(xNorm, -1.0f, 1.0f) * RANGO_TRACK * (TRACK_INVERTIR_X ? -1.0f : 1.0f);
  objetivoMano.y = saturar(yNorm, -1.0f, 1.0f) * RANGO_TRACK * (TRACK_INVERTIR_Y ? -1.0f : 1.0f);
  ultimoTrackMs = millis();

  detenerPrueba();
  if (estado != SIGUIENDO_MANO) {
    for (int u = 0; u < placasEncontradas * UNIDADES_POR_PLACA; u++) {
      if (unidadPrueba < 0 || u == unidadPrueba) {
        unidades[u].fase = U_MANO;
      }
    }
  }

  estado = SIGUIENDO_MANO;
}

bool enMovimiento() {
  return estado == PATRON || estado == REGRESANDO;
}

// PRUEBA UNIDAD POR UNIDAD (Monitor Serie)
//   u  elige la siguiente unidad (1, 2, ... 16, y luego "todas")
//   e  empieza el movimiento de prueba de la unidad elegida
//   p  lo pausa: la unidad regresa al centro
// El movimiento de prueba es arriba, abajo, izquierda, derecha y las
// dos diagonales, en ciclo

void empezarPrueba() {
  if (placasEncontradas == 0) {
    Serial.println("[PRUEBA] No hay placas PCA9685 conectadas");
    return;
  }
  if (unidadPrueba < 0) {
    unidadPrueba = 0;   // si no se eligió ninguna, empieza con la 1
  }
  irAlCentro();   // las demás regresan al centro
  Unidad& un = unidades[unidadPrueba];
  un.fase = U_PRUEBA;
  pasoPrueba = 0;
  llegoPruebaMs = 0;
  estado = PRUEBA;
  Serial.printf("[PRUEBA] Movimiento de prueba de la unidad %d (p = pausar)\n", unidadPrueba + 1);
}

void pausarPrueba() {
  if (estado != PRUEBA) {
    Serial.println("[PRUEBA] No hay movimiento de prueba en curso (e = empezar)");
    return;
  }
  detenerPrueba();
  Serial.println("[PRUEBA] Pausa: la unidad regresa al centro");
}

void siguienteUnidadPrueba() {
  bool estabaProbando = estado == PRUEBA;
  detenerPrueba();

  unidadPrueba++;
  if (unidadPrueba >= placasEncontradas * UNIDADES_POR_PLACA) {
    unidadPrueba = -1;
    Serial.println("[PRUEBA] Todas las unidades (e = empezar con la unidad 1)");
    return;
  }

  int b = unidadPrueba / UNIDADES_POR_PLACA;
  int k = unidadPrueba % UNIDADES_POR_PLACA;
  Serial.printf("[PRUEBA] Unidad %d elegida (PCA 0x%02X, canales %d=X y %d=Y)%s\n",
                unidadPrueba + 1, direccionPlaca[b], canalX(k), canalY(k),
                estabaProbando ? "" : "  e = empezar");
  if (estabaProbando) empezarPrueba();   // si ya estaba probando, sigue con la nueva
}

// =============================================
// AVANCE HACIA UN PUNTO (velocidad constante)
// Regresa true si ya llegó
// =============================================

bool avanzarHacia(Unidad& un, float x, float y, float velocidad) {
  float dx = x - un.x;
  float dy = y - un.y;
  float distancia = sqrtf(dx * dx + dy * dy);
  float paso = velocidad * TS_S;

  if (distancia <= paso) {
    un.x = x;
    un.y = y;
    return true;
  }

  un.x += dx / distancia * paso;
  un.y += dy / distancia * paso;
  return false;
}

// -----------------------------
// TURNOS (TRACKING y regreso al centro)
// -----------------------------
// Como el reloj de un CPU: cada paso de 20 ms solo TRACK_POR_TURNO
// unidades que aún no llegan dan un salto corto; el siguiente paso les
// toca a las siguientes, en ronda. Ninguna completa su movimiento de
// golpe: todas avanzan "a saltitos" casi al mismo tiempo, pero nunca
// arrancan más de 4 unidades (8 servos) juntas

int siguienteTurno = 0;   // por qué unidad empieza la siguiente ronda

void objetivoDe(const Unidad& un, float& x, float& y) {
  if (un.fase == U_MANO) { x = objetivoMano.x; y = objetivoMano.y; }
  else                   { x = 0.0f;           y = 0.0f; }
}

bool necesitaTurno(const Unidad& un) {
  if (un.fase != U_MANO && un.fase != U_REGRESO) return false;
  float x, y;
  objetivoDe(un, x, y);
  return fabsf(x - un.x) >= E_QUANT || fabsf(y - un.y) >= E_QUANT;
}

// Marca en 'turno' las unidades que se mueven en este paso y regresa
// el tamaño del salto (grados)
float elegirTurno(bool turno[]) {
  int pendientes = 0;
  for (int u = 0; u < NUM_UNIDADES; u++) {
    turno[u] = false;
    if (necesitaTurno(unidades[u])) pendientes++;
  }
  if (pendientes == 0) return 0.0f;

  // Cada unidad se mueve 1 de cada 'rondas' pasos: el salto se agranda
  // en esa proporción para que el promedio siga siendo VEL_TRACK
  int rondas = (pendientes + TRACK_POR_TURNO - 1) / TRACK_POR_TURNO;
  float salto = VEL_TRACK * TS_S * rondas;
  if (salto > TRACK_SALTO_MAX) salto = TRACK_SALTO_MAX;

  int elegidas = 0;
  for (int i = 0; i < NUM_UNIDADES && elegidas < TRACK_POR_TURNO; i++) {
    int u = (siguienteTurno + i) % NUM_UNIDADES;
    if (necesitaTurno(unidades[u])) {
      turno[u] = true;
      elegidas++;
      siguienteTurno = (u + 1) % NUM_UNIDADES;
    }
  }
  return salto;
}

// =============================================
// ACTUALIZAR (llamar en cada loop; corre cada 20 ms)
// =============================================

void actualizarMovimiento() {
  unsigned long ahora = micros();

  if ((unsigned long)(ahora - tControlUs) < TS_US) {
    return;
  }
  tControlUs += TS_US;

  // Si el loop se atrasó mucho, no intentar "alcanzar"
  if ((unsigned long)(ahora - tControlUs) > 5 * TS_US) {
    tControlUs = ahora;
  }

  float tPatron = (millis() - inicioPatronMs) / 1000.0f;

  if (estado == SIGUIENDO_MANO && millis() - ultimoTrackMs > TRACK_TIMEOUT_MS) {
    Serial.println("[MOV] Sin posicion de mano: regreso al centro");
    irAlCentro();
  }

  // -----------------------------
  // AVANZAR CADA UNIDAD
  // -----------------------------

  bool algunaActiva = false;

  bool turno[NUM_UNIDADES];
  float salto = elegirTurno(turno);

  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];

    switch (un.fase) {

      case U_FIGURA: {
        float tx, ty;
        bool sigue = objetivoFigura(patronActual, u, tPatron, tx, ty);
        seguirObjetivo(un, tx, ty);
        if (!sigue && fabsf(un.x) < E_QUANT && fabsf(un.y) < E_QUANT) {
          un.x = 0.0f;
          un.y = 0.0f;
          un.vx = 0.0f;
          un.vy = 0.0f;
          un.fase = U_QUIETA;
        }
        break;
      }

      case U_PRUEBA: {
        const PuntoPrueba& pp = PASOS_PRUEBA[pasoPrueba];
        if (llegoPruebaMs == 0) {
          if (avanzarHacia(un, pp.x * AMPLITUD, pp.y * AMPLITUD, VEL_PRUEBA)) {
            llegoPruebaMs = millis();
            Serial.printf("[PRUEBA] Unidad %d: %s\n", u + 1, pp.nombre);
          }
        } else if (millis() - llegoPruebaMs >= PAUSA_PRUEBA_MS) {
          pasoPrueba = (pasoPrueba + 1) % NUM_PASOS_PRUEBA;
          llegoPruebaMs = 0;
        }
        break;
      }

      case U_REGRESO:
        // Por turnos, para que un STOP o el fin del TRACKING no
        // regrese las 16 de golpe. El salto se escala a VEL_REGRESO
        if (!necesitaTurno(un)) {
          un.x = 0.0f;
          un.y = 0.0f;
          un.fase = U_QUIETA;
        } else if (turno[u] &&
                   avanzarHacia(un, 0.0f, 0.0f, salto * (VEL_REGRESO / VEL_TRACK) / TS_S)) {
          un.fase = U_QUIETA;
        }
        break;

      case U_MANO:
        // Solo se mueve cuando le toca turno (salto corto hacia la mano)
        if (turno[u]) {
          avanzarHacia(un, objetivoMano.x, objetivoMano.y, salto / TS_S);
        }
        break;

      case U_QUIETA:
        break;
    }

    if (un.fase != U_QUIETA) {
      algunaActiva = true;
    }
  }

  // ¿Terminó la tanda?
  if ((estado == PATRON && !algunaActiva) ||
      (estado == REGRESANDO && !algunaActiva)) {
    if (estado == PATRON) {
      Serial.printf("[MOV] Patron %s terminado\n", NOMBRES_PATRON[patronActual]);
    }
    estado = QUIETO;
  }

  aplicarServos();
}