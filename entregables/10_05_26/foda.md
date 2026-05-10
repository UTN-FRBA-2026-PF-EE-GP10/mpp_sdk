---
title: "Análisis FODA"
subtitle: "Tesis de Ingeniería Electrónica"
author: "Grupo 10"
date: "10 de mayo de 2026"
geometry: "margin=2.2cm"
fontsize: 11pt
mainfont: "DejaVu Serif"
sansfont: "DejaVu Sans"
monofont: "DejaVu Sans Mono"
colorlinks: true
linkcolor: "MidnightBlue"
urlcolor: "MidnightBlue"
header-includes:
  - \usepackage{amsmath}
  - \usepackage{amssymb}
  - \usepackage{graphicx}
  - \usepackage{titling}
  - \pretitle{\begin{center}\includegraphics[width=3.2cm]{../logo_UTN.pdf}\\[1em]\LARGE}
  - \posttitle{\par\end{center}\vskip 0.5em}
---

## 1. Contexto

El proyecto `mpp-sdk` da soporte a una tesis de Ingeniería Electrónica
sobre seguimiento del punto de máxima potencia (MPPT) en sistemas
fotovoltaicos. La entrega final consta de cuatro componentes: la
biblioteca en Python, un paper con el estudio comparativo, un
demostrador físico (Raspberry Pi 5 + Raspberry Pi Pico 2 / RP2350
comunicados por SPI + etapa SEPIC + panel pequeño) y un **algoritmo
final embebido en el microcontrolador**, validado punto a punto
contra la referencia en Python.

El presente análisis FODA se realiza al cierre de la fase de
**esquemático**: hay un *Pull Request* abierto (`hw/placa-sepic`) con
la primera versión, y todavía estamos a tiempo de mover decisiones de
topología, transistor de potencia, controlador de compuerta (*gate
driver*) y medición antes de pasar al diseño del circuito impreso.

## 2. Matriz FODA

## 2.1 Fortalezas (internas, positivas)

- **Arquitectura modular y verificable.** El SDK se separa en cuatro
  pilares (`models/`, `converters/`, `algorithms/`, `io/`) que se
  validan de forma independiente. El mismo código de control corre
  en simulación y en hardware sin modificaciones, lo que reduce el
  riesgo de divergencia entre simulación y realidad.
- **Base de simulación operativa.** El algoritmo Perturbar y
  Observar (P\&O) ya está implementado y funcionando contra el
  modelo `IdealSingleDiode` y el modelo del convertidor SEPIC. La
  integración con `pvlib` se hace mediante un único adaptador, sin
  reimplementar la física del panel.
- **Banco de comparación reproducible.** El proyecto incluye una
  pieza de software que ejecuta cada algoritmo contra perfiles fijos
  de irradiancia y temperatura, calcula las métricas (eficiencia de
  seguimiento, tiempo de establecimiento, oscilación en régimen) y
  genera las tablas y figuras que consume el paper. Permite que cada
  algoritmo nuevo se incorpore al estudio comparativo en un solo
  *Pull Request*.
- **Topología SEPIC bien justificada.** Permite que la tensión
  $V_\text{mpp}$ del panel esté por encima o por debajo de la
  tensión de carga sin cambiar la arquitectura, lo cual es ideal
  para un demostrador académico con un rango amplio de irradiancia.
- **Microcontrolador ya seleccionado: Raspberry Pi Pico 2 (RP2350).**
  La decisión está cerrada y elimina una variable importante del
  esquemático: PWM por hardware con bajo *jitter*, SDK en C bien
  soportado, doble núcleo Cortex-M33, 520 KB de SRAM y 4 MB de
  *flash*. Holgado frente al presupuesto del algoritmo a embarcar
  ($\le 16~\text{KB}$ de *flash*, $\le 4~\text{KB}$ de RAM,
  $\le 1~\text{ms}$ por paso de control).
- **Acceso a los laboratorios de la facultad.** Disponibilidad de
  osciloscopio, fuentes de alimentación, multímetros, soldador y
  banco general sin costo adicional. Es crítico para la puesta en
  marcha, la calibración de la cadena de medición y la
  caracterización del SEPIC contra el modelo.
- **Equipo con roles claros.** Tres integrantes, una persona por
  área (SDK, hardware, firmware), con reuniones semanales de
  coordinación.
- **Política de verificación explícita.** Cada módulo exige pruebas
  unitarias, una demostración independiente y una prueba de
  integración antes de su incorporación. Es una política defendible
  frente a un tribunal y compatible con la política de uso de modelos
  de lenguaje.
- **Trazabilidad reproducible.** Dependencias fijadas en `uv.lock`,
  etiquetas (*tags*) `vX.Y.Z` por hito, y figuras del paper
  generadas exclusivamente por *scripts* en `examples/` o
  `paper/figures/`.

## 2.2 Oportunidades (externas, positivas)

- **Nicho vacío en el ecosistema Python.** `pvlib` cubre la *física*
  del panel pero no incluye controladores de lazo cerrado. No existe
  una biblioteca abierta de algoritmos MPPT comparables; el proyecto
  puede ocupar ese espacio sin competir con `pvlib`. De hecho lo
  adopta como dependencia opcional.
- **Reproducibilidad simulación-realidad como contribución
  metodológica.** La mayor parte de la literatura MPPT usa
  MATLAB / Simulink con código no publicado y métricas particulares
  de cada paper. Un *framework* en Python que cierre el ciclo
  simulación → ensayo en lazo con hardware (HIL) → algoritmo
  embebido en MCU es publicable por sí mismo, aun si los algoritmos
  novedosos rinden de manera modesta.
- **El embebido en MCU como restricción de diseño favorable.**
  Sesga el trabajo hacia métodos de paso fijo y de poco estado
  interno, que son los más fáciles de analizar y defender en la
  tesis.
- **Componentes accesibles.** El RP2350 ya está fijado y es de bajo
  costo; los sensores INA226 y *shunt* + amplificador de
  instrumentación están en stock; los transistores GaN y SiC en
  encapsulado TO-220 / DPAK son piezas comunes.
- **Adopción posterior.** Si el SDK se publica en PyPI con el
  adaptador `pvlib` operativo, otros tesistas y grupos pueden
  incorporarlo y generar citas, fortaleciendo el aporte.

## 2.3 Debilidades (internas, negativas)

- **Capacidad horaria muy ajustada.** El presupuesto efectivo es de
  ≈ 600 h totales para 7 meses; cualquier atraso en hardware
  (fabricación, puesta en marcha, calibración) consume directamente
  del margen. La ganancia de productividad por uso de modelos de
  lenguaje (≈ ×2 sobre software y prosa) **no se transfiere al
  hardware**: la inteligencia artificial no lee un osciloscopio.
- **Sin experiencia previa con SEPIC en el equipo.** El algoritmo
  P\&O y la arquitectura del SDK están sólidos, pero el grupo no
  diseñó ni caracterizó previamente una placa SEPIC. La curva de
  aprendizaje cae sobre el camino crítico.
- **Decisiones de hardware aún abiertas.** GaN o SiC, sensor de
  corriente (INA226 vs *shunt* + amplificador vs Hall), frecuencia
  de conmutación y granularidad de la medición. Cada una cierra
  alternativas, y todas deben quedar fijas antes del cierre del
  bloque actual.
- **Una sola persona por camino crítico.** Si el responsable de
  hardware o de firmware no entrega en su bloque clave (PCB a
  fabricación, ensayo HIL), no hay redundancia real.
- **Cobertura de pruebas incipiente.** El árbol `tests/` existe pero
  la matriz de pruebas unitarias y de integración aún no cubre todos
  los pilares del SDK. Es una deuda explícita en `PLAN.md`.

## 2.4 Amenazas (externas, negativas)

- **Atraso en la fabricación del PCB.** El hito duro es **enviar el
  PCB a fabricación antes del fin de la semana 6**. Cualquier
  retraso del fabricante (plazos del ensamblado, retrabajo por
  errores en las huellas de componentes, demora aduanera) cascadea
  sobre el ensayo HIL y sobre el embebido del algoritmo en el MCU.
- **Componentes con plazo largo de entrega o discontinuados.**
  Algunos controladores de compuerta específicos y los transistores
  GaN de pinout no estándar pueden estar fuera de stock o exigir un
  pedido mínimo elevado. La selección debe favorecer alternativas de
  segunda fuente.
- **Sesgo del tribunal frente al uso de inteligencia artificial.**
  Aunque la política de divulgación está documentada, un revisor
  puede percibir el repositorio como "demasiado AI-asistido". La
  mitigación es la tabla de exposición por capa y el argumento
  metodológico preparado para la defensa (ver § 3).
- **Brecha simulación-realidad mayor a la tolerada.** Si la
  eficiencia de seguimiento medida en banco diverge significativamente
  de la simulada por motivos no identificados (parásitos, EMI, ruido
  en la cadena de medición), el reporte cuantitativo del paper se
  debilita.
- **Restricción de tiempo real en el lazo de control.** Linux en
  espacio de usuario sobre la Raspberry Pi 5 no garantiza el tiempo
  real necesario para PWM en el rango de kHz; el lazo rápido vive en
  el RP2350 por diseño. Si el RP2350 quedara subdimensionado para
  algún algoritmo en particular, se reescala el algoritmo, no el
  chip.

## 3. Resumen estratégico

| Cuadrante                 | Tema central                                                |
| ------------------------- | ----------------------------------------------------------- |
| **F**ortaleza dominante   | Arquitectura modular + acceso a laboratorios                |
| **O**portunidad dominante | Nicho vacío en MPPT abierto y reproducible (sim → MCU)      |
| **D**ebilidad dominante   | Horas ajustadas + falta de experiencia con SEPIC físico     |
| **A**menaza dominante     | Atraso de PCB y de componentes en el camino crítico         |

Las acciones de mayor apalancamiento durante el bloque actual son:

1. **Cerrar la selección de FET y controlador de compuerta en la
   semana 2.** Hasta que estén fijos, el resto del esquemático no
   puede iterar de forma productiva.
2. **Disparar el pedido de componentes de plazo largo en la semana
   4** con segundas fuentes ya identificadas, aunque el PCB esté
   todavía en revisión.
3. **Mantener un banco de respaldo con una placa de evaluación
   comercial**, para no bloquear la pista de software si el PCB
   propio se atrasa.
4. **Atar cada decisión de hardware a una métrica del SDK**: estado
   en bytes, microsegundos por paso, *flash* y RAM consumidos. De
   esa forma, la elección del algoritmo a embarcar cae alineada con
   el diseño físico.

\bigskip

**Sobre el uso de inteligencia artificial y el sesgo de revisión.**
La tesis se desarrolla sin financiamiento externo y compite con
grupos que sí cuentan con financiamiento o con asistencia masiva por
IA. *Adoptar* la IA como herramienta de productividad — bajo una
política documentada de divulgación, verificación y autoría humana —
no es un atajo, sino la única forma realista de cerrar la brecha de
recursos sin sacrificar el alcance. La discusión completa se
encuentra en `PLAN.md` y en `README.md`.
