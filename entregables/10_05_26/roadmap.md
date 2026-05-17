---
title: "Diagrama temporal de entregables y desafíos"
subtitle: "Tesis de Ingeniería Electrónica"
author: "Grupo 10"
date: "10 de mayo de 2026"
geometry: "margin=2cm"
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
  - \usepackage{tikz}
  - \usetikzlibrary{positioning,arrows.meta,shapes.geometric,fit,backgrounds,calc}
  - \usepackage{pdflscape}
  - \usepackage{graphicx}
  - \usepackage{titling}
  - \pretitle{\begin{center}\includegraphics[width=3.2cm]{../logo_UTN.pdf}\\[1em]\LARGE}
  - \posttitle{\par\end{center}\vskip 0.5em}
---

## 1. Marco temporal

El proyecto se ejecuta en **7 meses (≈ 30 semanas)** con un techo
blando de 8 meses, organizado en **siete bloques de cuatro semanas**.
Tres integrantes a 6 horas semanales nominales.

Hay **dos hitos duros** que dominan el cronograma:

| # | Hito                                  | Vencimiento     | Riesgo si se incumple                                                             |
|---|---------------------------------------|-----------------|-----------------------------------------------------------------------------------|
| 1 | **Envío del PCB a fabricación**       | Fin de semana 6 | Cascadea sobre el ensayo HIL y sobre el embebido del algoritmo en el MCU          |
| 2 | **Ensayo HIL extremo a extremo**      | Fin de semana 16| El paper retrocede a una contribución solo por simulación (modo degradado)        |

## 2. Diagrama en bloques

El diagrama (página siguiente) se lee de izquierda a derecha en
sentido temporal y por *streams* horizontales:

- **Stream A — SDK e integración.** Código en Python, paper, CI.
- **Stream B — Banco de pruebas.** Esquemático, PCB, ensayos en banco.
- **Stream C — Hardware/Firmware.** Raspberry Pi Pico 2 (RP2350), HIL y
  embebido del algoritmo final.

Las flechas continuas son dependencias dentro de un mismo *stream*.
Las flechas punteadas son acoples entre *streams* y se distinguen por
color (verde para el protocolo SPI entre A y C, magenta para el
embebido del algoritmo de A a C). Los bloques en rojo son los hitos
duros; el bloque en amarillo es la posición actual del proyecto.

<!-- markdownlint-disable MD013 -->
\begin{landscape}
\thispagestyle{empty}
\vspace*{\fill}
\begin{center}
\resizebox{\linewidth}{!}{%
\begin{tikzpicture}[
  x=3.8cm, y=2.5cm,
  block/.style={
    rectangle, draw=black!60, rounded corners=2pt, thick,
    minimum width=2.8cm, minimum height=1.6cm,
    align=center, font=\footnotesize,
    inner sep=3pt, fill=blue!5
  },
  hard/.style={block, fill=red!20, draw=red!70, very thick},
  here/.style={block, fill=yellow!35, draw=orange!85, very thick},
  arrow/.style={-{Stealth[length=2.8mm]}, thick, black!65},
  crossSPI/.style={-{Stealth[length=2.4mm]}, dashed, very thick, teal!75!black},
  crossPort/.style={-{Stealth[length=2.4mm]}, dashed, very thick, magenta!75!black},
  hdr/.style={font=\small\bfseries, anchor=south, align=center},
  lane/.style={font=\small\bfseries, anchor=east, align=right},
  mile/.style={font=\scriptsize\itshape, anchor=north, align=center, text=red!70!black}
]

% --- Encabezados ---
\foreach \i/\name/\wks in {%
  1/Fundación/sem 1--4,
  2/{Simulación y SPI}/sem 5--8,
  3/{Encendido del HW}/sem 9--12,
  4/HIL/sem 13--16,
  5/{Empuje algorítmico}/sem 17--20,
  6/{Embebido en MCU}/sem 21--24,
  7/Redacción/sem 25--30%
} {
  \node[hdr] at (\i, 3.15) {Bloque \i \\ \textsc{\name} \\ \scriptsize \wks};
}

% --- Etiquetas de fila ---
\node[lane] at (0.45, 2) {A — SDK e \\ integración};
\node[lane] at (0.45, 1) {B — Banco de \\ pruebas};
\node[lane] at (0.45, 0) {C — Hardware/\\ Firmware};

% --- Fila A: SDK ---
\node[here]  (a1) at (1, 2) {Lossy + Array \\ in-tree; pvlib \\ (esqueleto)};
\node[block] (a2) at (2, 2) {InCond, P\&O \\ adaptativo, \\ banco comp.};
\node[block] (a3) at (3, 2) {Adaptador \\ pvlib \\ integrado};
\node[block] (a4) at (4, 2) {Sim + HIL en \\ banco comp.; \\ figs prelim.};
\node[block] (a5) at (5, 2) {Global-MPPT; \\ 1as figuras \\ del paper};
\node[block] (a6) at (6, 2) {Algoritmo a \\ embarcar; \\ figuras fijas};
\node[block] (a7) at (7, 2) {Paper: borrador \\ $\to$ revisión \\ $\to$ pulido};

% --- Fila B: Hardware ---
\node[here]  (b1) at (1, 1) {Topología; FET \\ + gate driver; \\ esquemático v1};
\node[hard]  (b2) at (2, 1) {PCB v1; \\ \textbf{a fab. sem 6}; \\ pedido componentes};
\node[block] (b3) at (3, 1) {Ensamblado + \\ puesta en marcha + \\ ADC calibrado};
\node[block] (b4) at (4, 1) {Cadena de medición \\ validada vs \\ osciloscopio};
\node[block] (b5) at (5, 1) {Verif. cruzada \\ HW vs sim en \\ varios puntos};
\node[block] (b6) at (6, 1) {Ensayo con \\ panel real \\ (objetivo extendido)};
\node[block] (b7) at (7, 1) {Capítulo HW + \\ BOM + \\ calibración};

% --- Fila C: Firmware ---
\node[block] (c1) at (1, 0) {Encendido RP2350; \\ ADC/PWM/SPI \\ (esqueleto)};
\node[block] (c2) at (2, 0) {Protocolo SPI \\ cerrado; \\ HIL en lazo loc.};
\node[block] (c3) at (3, 0) {Jitter ADC/PWM \\ medido; SPI \\ a Pi vivo};
\node[hard]  (c4) at (4, 0) {Fase 5a: \\ HIL extremo \\ a extremo};
\node[block] (c5) at (5, 0) {Inicio del \\ embebido Python \\ $\to$ MCU};
\node[hard]  (c6) at (6, 0) {Fase 5b: \\ algoritmo \\ embebido};
\node[block] (c7) at (7, 0) {Capítulo FW \\ + reporte de \\ recursos};

% --- Flechas horizontales (dependencias dentro del stream) ---
\foreach \r in {a,b,c} {
  \foreach \i in {1,...,6} {
    \pgfmathtruncatemacro{\j}{\i+1}
    \draw[arrow] (\r\i.east) -- (\r\j.west);
  }
}

% --- Acoples entre streams (ruteados por los pasillos entre columnas) ---
% SPI (verde teal): A2 -> C2 por el pasillo en x = 2.5
\draw[crossSPI, rounded corners=6pt]
  (a2.south) -- (2, 1.45) -- (2.5, 1.45) -- (2.5, 0.55) -- (2, 0.55) -- (c2.north);

% Embebido (magenta): A5 -> C5 por el pasillo en x = 5.5
\draw[crossPort, rounded corners=6pt]
  (a5.south) -- (5, 1.45) -- (5.5, 1.45) -- (5.5, 0.55) -- (5, 0.55) -- (c5.north);

% --- Tira inferior de hitos ---
\draw[red!60, thick] (0.5, -1.1) -- (7.5, -1.1);
\foreach \x in {1,2,4,7} {
  \fill[red!70] (\x, -1.1) circle (2pt);
}
\node[mile] at (1, -1.2) {[HOY] PR del esquemático};
\node[mile] at (2, -1.2) {Hito 1: PCB $\to$ fab.};
\node[mile] at (4, -1.2) {Hito 2: HIL E2E};
\node[mile] at (7, -1.2) {Defensa};

% --- Referencia ---
\node[anchor=north west, font=\scriptsize, draw=black!40, rounded corners=1pt, inner sep=4pt]
  at (0.0, -1.8) {%
    \begin{tabular}{@{}ll@{}}
    \tikz \fill[red!20, draw=red!70] (0,0) rectangle (0.4,0.25); & Hito duro \\
    \tikz \fill[yellow!35, draw=orange!85] (0,0) rectangle (0.4,0.25); & Posición actual \\
    \tikz \fill[blue!5, draw=black!60] (0,0) rectangle (0.4,0.25); & Entregable regular \\
    \tikz[baseline=0pt] \draw[-{Stealth[length=2mm]}, thick, black!65] (0,0.1) -- (0.5,0.1); & Dependencia dentro del mismo stream \\
    \tikz[baseline=0pt] \draw[-{Stealth[length=2mm]}, dashed, very thick, teal!75!black] (0,0.1) -- (0.5,0.1); & Acople A$\leftrightarrow$C: protocolo SPI (Pi $\leftrightarrow$ RP2350) \\
    \tikz[baseline=0pt] \draw[-{Stealth[length=2mm]}, dashed, very thick, magenta!75!black] (0,0.1) -- (0.5,0.1); & Acople A$\leftrightarrow$C: embebido del algoritmo Python $\to$ MCU \\
    \end{tabular}%
  };

\end{tikzpicture}%
}
\end{center}
\vspace*{\fill}
\end{landscape}
<!-- markdownlint-enable MD013 -->

## 3. Entregables por bloque

| Bloque | Entregable A (SDK)                            | Entregable B (Banco de pruebas)                        | Entregable C (Hardware/Firmware, RP2350)             |
|-------:|-----------------------------------------------|---------------------------------------------------------|------------------------------------------------------|
| 1      | `lossy.py`, `array.py`, esqueleto del adaptador `pvlib` | Esquemático v1, BOM, FET y controlador de compuerta | Esqueleto de ADC, PWM y SPI esclavo                  |
| 2      | InCond, P\&O adaptativo, banco de comparación (esqueleto) | PCB v1, **fab. por sem 6**, pedido de componentes  | Protocolo SPI cerrado, HIL en lazo local             |
| 3      | Adaptador `pvlib` integrado                   | PCB ensamblada, ADC calibrado                           | Jitter medido, enlace a la Pi vivo                   |
| 4      | Simulación + HIL en el banco de comparación   | Cadena de medición validada vs osciloscopio             | **Fase 5a — HIL extremo a extremo [OK]**             |
| 5      | Un Global-MPPT + primeras figuras del paper   | Verificación cruzada HW vs sim                          | Inicio del embebido Python $\to$ MCU                 |
| 6      | Decisión del algoritmo a embarcar             | Ensayo con panel real (objetivo extendido)              | **Fase 5b — algoritmo embebido en el MCU [OK]**      |
| 7      | Paper: borrador $\to$ pulido                  | Capítulo de hardware + BOM + calibración                | Capítulo de firmware + reporte de recursos           |

## 4. Principales desafíos a resolver

### 4.1 Bloque actual — Fundación (semanas 1–4)

1. **Cierre de topología SEPIC y selección del transistor de potencia
   (FET).** GaN o SiC, encapsulado, alternativas de segunda fuente.
   Bloquea el pinout del controlador de compuerta y el cálculo de
   disipación térmica.
2. **Selección del controlador de compuerta (*gate driver*).**
   Compatible con el FET elegido, con pico de corriente suficiente,
   con alimentación *bootstrap* o aislamiento si el esquema lo
   requiere.
3. **Medición de tensión y corriente.** Sensor INA226 (I²C,
   integrado) o *shunt* + amplificador de instrumentación. Definir
   el lado del *shunt* (alto o bajo) y su impacto sobre el ADC del
   RP2350.
4. **Frecuencia de conmutación.** Compromiso entre tamaño de los
   inductores $L_1$, $L_2$ y del capacitor de acople $C_a$ del SEPIC,
   y pérdidas de conmutación. Una vez fijada, se cierran los valores
   nominales.
5. **Protecciones básicas.** Protección contra sobrecorriente (OCP)
   por hardware, sobre-tensión (OVP) en panel y carga, y arranque
   suave (*soft-start*). Mínimas pero no opcionales: la primera
   placa no se destruye en la puesta en marcha.

## 4.2 Bloques 2–4 — camino crítico hasta el HIL

1. **Diseño del circuito impreso (PCB).** Lazos de conmutación
   cortos, plano de retorno limpio en alta frecuencia, conexión
   *kelvin* del *shunt*, separación de tierras analógica y digital,
   huellas de componentes verificadas antes del envío a fabricación.
2. **Riesgo de atraso de fabricación y componentes con plazo largo
   de entrega.** Disparar el pedido del controlador de compuerta y
   los FETs en la semana 4 con alternativas ya elegidas. Mantener un
   banco de respaldo con una placa de evaluación comercial, para no
   bloquear el *stream* de firmware si el PCB propio se atrasa.
3. **Calibración de la cadena de medición.** Escala y desviación
   (*offset*) del ADC, valor real del *shunt*, ancho de banda del
   *front-end*. Es necesaria antes de comparar contra simulación.
4. **Diseño del protocolo SPI (Pi $\leftrightarrow$ RP2350).** Roles
   de maestro y esclavo, formato de trama, frecuencia de muestreo,
   semántica del *watchdog* y del paro suave (*soft-stop*).
   Documentar en `data/hardware/spi_protocol.md` apenas se
   estabilice.
5. **Cierre de la brecha simulación-realidad.** Tolerancia
   documentada entre la eficiencia simulada y la medida; si diverge
   más de lo esperado, refinar el modelo del SEPIC ($R_{DS,on}$, DCR
   del inductor, $V_F$ del diodo) en lugar de "ajustar" números.

## 4.3 Bloques 5–6 — embebido del algoritmo en el MCU

1. **Embebido del algoritmo en el RP2350.** Reescribir P\&O o InCond
   en C (Pi Pico SDK) o MicroPython, respetando el presupuesto:

   $$\text{flash} \le 16~\text{KB}, \quad
     \text{RAM} \le 4~\text{KB}, \quad
     t_\text{paso} \le 1~\text{ms}.$$

2. **Verificación cruzada punto a punto.** Las trazas $(V, I, D)$
   capturadas en la Fase 5a se reproducen en la Fase 5b dentro de
   una tolerancia numérica documentada.
3. **Reporte de uso de recursos.** Tamaño del código compilado, pico
   de RAM, latencia del paso de control, energía por paso. Es la
   métrica que sostiene la afirmación *"algoritmo embebible en MCU"*
   del paper.

## 4.4 Riesgos transversales

| Riesgo                                              | Mitigación                                                                       |
|-----------------------------------------------------|----------------------------------------------------------------------------------|
| Atraso del PCB                                      | Topología fijada en sem. 2, fabricación en sem. 6, banco de respaldo en paralelo |
| Algoritmo que no entra en el presupuesto del MCU    | Si solo entra P\&O de paso fijo, **es un resultado válido del paper**            |
| Caída de un integrante en el camino crítico         | La persona del SDK queda en superficie de integración (no crítico)               |
| Sesgo del tribunal sobre el uso de IA               | Tabla de exposición por capa + argumento metodológico (ver `README.md`)          |
| Brecha simulación-realidad fuera de tolerancia      | Refinar el modelo del SEPIC con parásitos medidos; documentar la tolerancia      |

## 5. Definición de "hecho" por entregable

Se considera *hecho* (tanto un módulo de software como un
sub-bloque de hardware) sólo cuando cumple las tres condiciones
exigidas por `PLAN.md`:

1. **Pruebas unitarias** que ejercitan la API pública en
   aislamiento.
2. **Demostración independiente** ejecutable a mano, que produce un
   único gráfico interpretable.
3. **Prueba de integración** que conecta el módulo al lazo completo
   (panel + convertidor + algoritmo + visualización o banco
   físico).

Para los hitos de hardware esto se traduce en: medición con
osciloscopio o multímetro frente a una referencia, captura
guardada en `data/hardware/`, y comparación con la predicción
del modelo dentro de una tolerancia documentada.

Por ejemplo, para validar la relación de impedancias del SEPIC
ideal contra el banco se contrasta la predicción

$$R_\text{in} = \frac{(1-D)^2}{D^2}\, R_\text{load}$$

barriendo el ciclo de trabajo $D$ y midiendo la corriente de
entrada y la tensión del panel.
