---
title: "Planificación del Proyecto"
subtitle: "Secuenciación, Gantt, Holgura y Camino Crítico"
author: "Grupo 10 — Tesis de Ingeniería Electrónica"
date: "24 de mayo de 2026"
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
  - \usepackage{tikz}
  - \usetikzlibrary{positioning,arrows.meta,shapes.geometric,fit,backgrounds,calc}
  - \usepackage{pgfgantt}
  - \usepackage{pdflscape}
  - \usepackage{graphicx}
  - \usepackage{booktabs}
  - \usepackage{array}
  - \usepackage{xcolor}
  - \usepackage{colortbl}
  - \usepackage{multirow}
  - \usepackage{titling}
  - \pretitle{\begin{center}\includegraphics[width=3.2cm]{../logo_UTN.pdf}\\[1em]\LARGE}
  - \posttitle{\par\end{center}\vskip 0.5em}
  - \definecolor{colorA}{RGB}{173,216,230}
  - \definecolor{colorB}{RGB}{255,210,150}
  - \definecolor{colorC}{RGB}{180,230,180}
  - \definecolor{colorHard}{RGB}{255,160,160}
  - \definecolor{colorMile}{RGB}{220,50,50}
  - \definecolor{colorCrit}{RGB}{200,30,30}
  - \definecolor{colorHoy}{RGB}{255,220,80}
---

<!-- markdownlint-disable MD013 -->

## 1. Secuenciación de Actividades

El proyecto se organiza en **tres *streams* paralelos** durante 7 bloques
de 4 semanas (excepto el último, de 6 semanas), totalizando **30 semanas**
desde el 5 de mayo de 2026.

**Arquitectura de ejecución:** la Raspberry Pi 4/5 corre el SDK Python y el
algoritmo MPPT. El RP2040 (Pi Pico) actúa exclusivamente como **proxy I/O**:
lee V/I por ADC y acciona el transistor por PWM, conectado a la RPi por SPI.
No es necesario portar el algoritmo al MCU; esa tarea queda como objetivo
extendido (*stretch*).

**Referencia temporal:**

- Semana 1 comienza el **5 de mayo de 2026**.
- Cada bloque abarca $\approx$ 1 mes; el bloque 7 tiene 6 semanas.
- **Hoy (24 de mayo de 2026)** = semana 3, dentro del bloque 1.

\begin{table}[h!]
\centering
\footnotesize
\setlength{\tabcolsep}{4pt}
\begin{tabular}{c l c c c l}
\toprule
\textbf{ID} & \textbf{Actividad} & \textbf{Bloque} & \textbf{Sem. inicio} & \textbf{Sem. fin} & \textbf{Predecesoras}\\
\midrule
\rowcolor{colorA!50}
A1 & Modelos \texttt{lossy}, \texttt{array}, esqueleto \texttt{pvlib} & 1 & 1 & 4 & ---\\
\rowcolor{colorA!30}
A2 & InCond, P\&O adaptativo, harness (esq.) + def.\ SPI & 2 & 5 & 8 & A1\\
\rowcolor{colorA!50}
A3 & Adaptador \texttt{pvlib} integrado & 3 & 9 & 12 & A2\\
\rowcolor{colorA!30}
A4 & Sim + HIL en harness; figuras preliminares & 4 & 13 & 16 & A3, \textit{C4}\\
\rowcolor{colorA!50}
A5 & Global-MPPT; primeras figuras del paper & 5 & 17 & 20 & A4\\
\rowcolor{colorA!30}
A6 & Algoritmo a implementar; figuras congeladas & 6 & 21 & 24 & A5\\
\rowcolor{colorA!50}
A7 & Paper: borrador $\to$ revisión $\to$ pulido & 7 & 25 & 30 & A6, B7\\
\midrule
\rowcolor{colorB!50}
B1 & Topología SEPIC, FET/gate-driver, esquemático v1 & 1 & 1 & 4 & ---\\
\rowcolor{colorB!30}
B2 & PCB v1; \textbf{a fab.\ sem.\ 6}; pedido de componentes & 2 & 5 & 8 & B1\\
\rowcolor{colorB!50}
B3 & PCB ensamblada, puesta en marcha, ADC calibrado & 3 & 9 & 12 & B2\\
\rowcolor{colorB!30}
B4 & Cadena de medición validada vs.\ osciloscopio & 4 & 13 & 16 & B3\\
\rowcolor{colorB!50}
B5 & Verificación cruzada HW vs.\ simulación & 5 & 17 & 20 & B4, \textit{C4}\\
\rowcolor{colorB!30}
B6 & \textbf{Ensayo con panel real bajo irradiancia variable} & 6 & 21 & 24 & B5\\
\rowcolor{colorB!50}
B7 & Capítulo HW + BOM + calibración & 7 & 25 & 30 & B5, B6\\
\midrule
\rowcolor{colorC!50}
C1 & Encendido RP2040; ADC/PWM/SPI proxy (esq.) & 1 & 1 & 4 & ---\\
\rowcolor{colorC!30}
C2 & Protocolo SPI cerrado; HIL en lazo local & 2 & 5 & 8 & C1, \textit{A2}\\
\rowcolor{colorC!50}
C3 & Jitter ADC/PWM medido; enlace SPI a Pi vivo & 3 & 9 & 12 & C2, \textit{B3}\\
\rowcolor{colorC!30}
C4 & \textbf{HIL extremo a extremo} [hito duro] & 4 & 13 & 16 & C3, B4\\
\rowcolor{colorC!50}
C7 & Capítulo FW + informe HIL & 7 & 25 & 30 & C4\\
\midrule
\rowcolor{colorC!20}
C5 & \emph{(stretch)} Inicio embebido algoritmo $\to$ MCU & 5 & 17 & 20 & C4, \textit{A5}\\
\rowcolor{colorC!10}
C6 & \emph{(stretch)} Algoritmo embebido en MCU validado & 6 & 21 & 24 & C5\\
\bottomrule
\end{tabular}
\caption{Secuenciación completa. Predecesoras en \emph{itálica} = acoples entre streams.}
\end{table}

**Dependencias entre *streams*:**

- **A2 → C2** (SPI): la interfaz `SpiMcuSource` del SDK fija el formato de trama del proxy.
- **B3 → C3** (PCB): la placa debe estar ensamblada antes de medir jitter y levantar el enlace.
- **B4 + C3 → C4** (HIL): requiere cadena de medición validada *y* SPI funcional.
- **C4 → A4** (harness): los resultados HIL se incorporan al banco de comparación.
- **A6 + B7 → A7** (paper): SDK y capítulo HW convergen en el borrador; C7 también contribuye.
- **(stretch) A5 → C5**: solo si se decide portar el algoritmo al MCU.

---

## 2. Diagrama de Gantt

\begin{landscape}
\thispagestyle{empty}
\vspace*{\fill}
\begin{center}
\resizebox{\linewidth}{!}{%
\begin{ganttchart}[
    x unit=0.58cm,
    y unit title=0.50cm,
    y unit chart=0.46cm,
    vgrid={*{3}{draw=gray!15,thin},{draw=gray!45,dashed,thin}},
    hgrid={draw=gray!20,thin},
    title height=1,
    title label font=\scriptsize\bfseries,
    bar label font=\scriptsize,
    group label font=\small\bfseries,
    bar/.append style={fill=blue!15, draw=blue!40},
    milestone/.append style={fill=colorMile, draw=colorMile!80!black, shape=diamond},
    today=3,
    today rule/.style={draw=orange!80, very thick, dashed},
    today label={\scriptsize\bfseries HOY},
    today label node/.append style={anchor=south west,
      font=\scriptsize\bfseries, text=orange!80!black}
]{1}{30}
  %% Títulos de meses
  \gantttitle{Mayo 2026}{4}
  \gantttitle{Junio 2026}{4}
  \gantttitle{Julio 2026}{4}
  \gantttitle{Agosto 2026}{4}
  \gantttitle{Septiembre 2026}{4}
  \gantttitle{Octubre 2026}{4}
  \gantttitle{Noviembre 2026}{6}\\
  \gantttitlelist{1,...,30}{1}\\

  %% Stream A
  \ganttgroup[group/.append style={fill=colorA!70, draw=colorA!90!black}]
    {A — SDK}{1}{30}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A1 Modelos + pvlib}{1}{4}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A2 Harness + InCond}{5}{8}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A3 pvlib adapter}{9}{12}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A4 Sim+HIL harness}{13}{16}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A5 Global-MPPT}{17}{20}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A6 Lock algoritmo}{21}{24}\\
  \ganttbar[bar/.append style={fill=colorA, draw=colorA!80!black}]
    {A7 Paper}{25}{30}\\

  %% Stream B
  \ganttgroup[group/.append style={fill=colorB!70, draw=colorB!90!black}]
    {B — Hardware}{1}{30}\\
  \ganttbar[bar/.append style={fill=colorB, draw=colorB!80!black}]
    {B1 Topología + esq.}{1}{4}\\
  \ganttbar[bar/.append style={fill=colorHard, draw=red!70}]
    {B2 PCB fab. sem.6}{5}{8}\\
  \ganttbar[bar/.append style={fill=colorB, draw=colorB!80!black}]
    {B3 Ensamblado + cal.}{9}{12}\\
  \ganttbar[bar/.append style={fill=colorB, draw=colorB!80!black}]
    {B4 Medición vs osc.}{13}{16}\\
  \ganttbar[bar/.append style={fill=colorB, draw=colorB!80!black}]
    {B5 HW vs sim}{17}{20}\\
  \ganttbar[bar/.append style={fill=colorB, draw=colorB!80!black}]
    {B6 Panel real}{21}{24}\\
  \ganttbar[bar/.append style={fill=colorB, draw=colorB!80!black}]
    {B7 Cap. HW + BOM}{25}{30}\\

  %% Stream C
  \ganttgroup[group/.append style={fill=colorC!70, draw=colorC!90!black}]
    {C — Firmware (RP2040)}{1}{30}\\
  \ganttbar[bar/.append style={fill=colorC, draw=colorC!80!black}]
    {C1 RP2040 ADC/PWM/SPI}{1}{4}\\
  \ganttbar[bar/.append style={fill=colorC, draw=colorC!80!black}]
    {C2 SPI + HIL local}{5}{8}\\
  \ganttbar[bar/.append style={fill=colorC, draw=colorC!80!black}]
    {C3 Jitter + SPI a Pi}{9}{12}\\
  \ganttbar[bar/.append style={fill=colorHard, draw=red!70}]
    {C4 HIL E2E}{13}{16}\\
  \ganttbar[bar/.append style={fill=colorB!40, draw=colorB!60, dashed}]
    {C5 Embebido MCU (stretch)}{17}{20}\\
  \ganttbar[bar/.append style={fill=colorB!40, draw=colorB!60, dashed}]
    {C6 MCU validado (stretch)}{21}{24}\\
  \ganttbar[bar/.append style={fill=colorC, draw=colorC!80!black}]
    {C7 Capítulo FW + informe HIL}{25}{30}\\

  %% Hitos duros
  \ganttmilestone[milestone/.append style={fill=colorHard, draw=red!70},
    milestone label font=\tiny\bfseries]{M1 PCB fab.}{8}\\
  \ganttmilestone[milestone/.append style={fill=colorHard, draw=red!70},
    milestone label font=\tiny\bfseries]{M3 HIL E2E}{16}\\
  \ganttmilestone[milestone/.append style={fill=colorHard, draw=red!70},
    milestone label font=\tiny\bfseries]{M5 Panel real}{24}\\
  \ganttmilestone[milestone/.append style={fill=colorMile, draw=colorMile!80!black},
    milestone label font=\tiny\bfseries]{M7 Defensa}{30}

\end{ganttchart}%
}% fin \resizebox

\vspace{0.4em}
\scriptsize
\textbf{Leyenda:}\quad
\tikz\fill[colorA,draw=colorA!80](0,0)rectangle(0.5,0.22);~Stream A (SDK)\quad
\tikz\fill[colorB,draw=colorB!80](0,0)rectangle(0.5,0.22);~Stream B (HW)\quad
\tikz\fill[colorC,draw=colorC!80](0,0)rectangle(0.5,0.22);~Stream C (FW)\quad
\tikz\fill[colorHard,draw=red!70](0,0)rectangle(0.5,0.22);~Hito duro\quad
\tikz\fill[colorB!40,draw=colorB!60](0,0)rectangle(0.5,0.22);~Stretch\quad
\tikz\draw[orange!80,very thick,dashed](0,0.11)--(0.6,0.11);~Hoy (sem.\ 3)

\end{center}
\vspace*{\fill}
\end{landscape}

---

## 3. Holgura del Proyecto

Se aplica el **Método del Camino Crítico (CPM)**. Para cada actividad:

$$
\text{TF} = \text{LS} - \text{ES} = \text{LF} - \text{EF}
$$

donde ES/EF son inicio/fin más temprano y LS/LF son inicio/fin más tardío.
El horizonte es $T = 30$ semanas.

\begin{table}[h!]
\centering
\footnotesize
\setlength{\tabcolsep}{4pt}
\newcommand{\crit}{\cellcolor{colorHard!55}\textbf{0}}
\begin{tabular}{c l c c c c c c}
\toprule
\textbf{ID} & \textbf{Actividad} & \textbf{Dur.} &
\textbf{ES} & \textbf{EF} & \textbf{LS} & \textbf{LF} & \textbf{TF}\\
\midrule
\rowcolor{colorA!30}
A1 & Modelos base + pvlib esq. & 4 & 1 & 4 & 1 & 4 & \crit\\
\rowcolor{colorA!20}
A2 & InCond + P\&O ad.\ + harness & 4 & 5 & 8 & 5 & 8 & \crit\\
\rowcolor{colorA!30}
A3 & pvlib integrado & 4 & 9 & 12 & 9 & 12 & \crit\\
\rowcolor{colorA!20}
A4 & Sim + HIL en harness & 4 & 13 & 16 & 13 & 16 & \crit\\
\rowcolor{colorA!30}
A5 & Global-MPPT + figs.\ paper & 4 & 17 & 20 & 17 & 20 & \crit\\
\rowcolor{colorA!20}
A6 & Algoritmo a embarcar & 4 & 21 & 24 & 21 & 24 & \crit\\
\rowcolor{colorA!30}
A7 & Paper borrador $\to$ pulido & 6 & 25 & 30 & 25 & 30 & \crit\\
\midrule
\rowcolor{colorB!30}
B1 & Topología + FET + esq.\ v1 & 4 & 1 & 4 & 1 & 4 & \crit\\
\rowcolor{colorB!20}
B2 & PCB v1 + a fab. & 4 & 5 & 8 & 5 & 8 & \crit\\
\rowcolor{colorB!30}
B3 & Ensamblado + puesta en marcha & 4 & 9 & 12 & 9 & 12 & \crit\\
\rowcolor{colorB!20}
B4 & Medición validada vs.\ osc. & 4 & 13 & 16 & 13 & 16 & \crit\\
\rowcolor{colorB!30}
B5 & Verif.\ cruzada HW vs.\ sim. & 4 & 17 & 20 & 17 & 20 & \crit\\
\rowcolor{colorB!20}
B6 & Ensayo con panel real & 4 & 21 & 24 & 21 & 24 & \crit\\
\rowcolor{colorB!30}
B7 & Capítulo HW + BOM & 6 & 25 & 30 & 25 & 30 & \crit\\
\midrule
\rowcolor{colorC!30}
C1 & RP2040 proxy ADC/PWM/SPI & 4 & 1 & 4 & 1 & 4 & \crit\\
\rowcolor{colorC!20}
C2 & Protocolo SPI + HIL local & 4 & 5 & 8 & 5 & 8 & \crit\\
\rowcolor{colorC!30}
C3 & Jitter medido + SPI a Pi & 4 & 9 & 12 & 9 & 12 & \crit\\
\rowcolor{colorC!20}
C4 & HIL extremo a extremo & 4 & 13 & 16 & 13 & 16 & \crit\\
\rowcolor{colorC!30}
C7 & Capítulo FW + informe HIL & 6 & 25 & 30 & 25 & 30 & 7\\
\midrule
\rowcolor{gray!15}
C5 & \emph{(stretch)} Embebido algoritmo $\to$ MCU & 4 & --- & --- & --- & --- & $\infty$\\
\rowcolor{gray!10}
C6 & \emph{(stretch)} Algoritmo embebido validado & 4 & --- & --- & --- & --- & $\infty$\\
\bottomrule
\end{tabular}
\caption{Holguras totales (TF) en semanas. Celdas \colorbox{colorHard!55}{\textbf{rojas}} = camino crítico (TF\,=\,0).
  C7 tiene TF\,=\,7 (redacción flexible). C5/C6 son stretch sin fecha obligatoria.}
\end{table}

**Interpretación:**

- **B5 y B6 ahora tienen TF=0.** El ensayo con panel real es requerido para el paper.
  La cadena B4→B5→B6→B7 llena exactamente los bloques 4–7 sin margen.
- **C5/C6 — opcionales.** El algoritmo corre en la Raspberry Pi 4/5; el RP2040 solo
  acciona el transistor (proxy I/O). Portar el algoritmo al MCU queda como stretch.
- **C7 — TF=7 semanas.** El capítulo de firmware está planificado en el bloque 7
  (semanas 25–30); esa holgura indica que su redacción es flexible y no condiciona
  la fecha final de entrega mientras se mantenga dentro de esa planificación.
- **Riesgo principal:** B2 (PCB a fabricación, sem. 6) tiene espera externa de 2–3
  semanas. Un atraso arrastra B3→B4→C4 y amenaza el hito duro HIL (semana 16).
  Con B6 ahora crítica, el mismo atraso también impacta el ensayo real.

---

## 4. Camino Crítico

### Rutas de longitud máxima

Existen **tres rutas de 30 semanas** — todas críticas:

| Ruta | Cadena de actividades | Duración |
|------|----------------------|----------|
| SDK | A1→A2→A3→A4→A5→A6→A7 | 30 sem. |
| HW completa | B1→B2→B3→B4→B5→B6→B7 | 30 sem. |
| FW→SDK | C1→C2→C3→C4→A4→A5→A6→A7 | 30 sem. |

C5 y C6 (embebido MCU) son **opcionales** y no pertenecen al camino crítico.

**Nodos de convergencia de alto riesgo:**

1. **C4 — HIL E2E (semana 16):** requiere B4 *y* C3 completos simultáneamente.
   Si el PCB se atrasa (B2/B3), arrastra directamente a C4.
2. **A7 — Paper (semana 25):** requiere A6 *y* B7. B7 a su vez requiere B6
   (ensayo real), que requiere sistema HIL funcional (C4).

### Diagrama de red con camino crítico

\begin{center}
\resizebox{\linewidth}{!}{%
\begin{tikzpicture}[
  x=2.1cm, y=2.2cm,
  %% Estilos de nodo
  base/.style={rectangle, rounded corners=3pt, thick,
               minimum width=1.5cm, minimum height=0.6cm,
               align=center, font=\small},
  nA/.style={base, fill=colorA,   draw=blue!60!black,   line width=1.2pt},
  nB/.style={base, fill=colorB,   draw=orange!70!black, line width=1.2pt},
  nC/.style={base, fill=colorC,   draw=green!55!black,  line width=1.2pt},
  nH/.style={base, fill=colorHard,draw=red!70,          line width=2pt},
  nS/.style={base, fill=colorB!35,draw=colorB!60,       line width=0.8pt, dashed},
  %% Estilos de flecha
  arr/.style={-{Stealth[length=3mm]}, line width=1.4pt},
  aA/.style={arr, blue!55},
  aB/.style={arr, orange!65},
  aC/.style={arr, green!50!black},
  cross/.style={arr, teal!60!black,   line width=1.2pt, dashed},
  crossM/.style={arr, magenta!60!black, line width=1.2pt, dashed}
]

%% ---- Fondos de swimlane ----
\fill[colorA!8]  (-0.55,2.55) rectangle (7.55,3.55);
\fill[colorB!8]  (-0.55,1.25) rectangle (7.55,2.25);
\fill[colorC!8]  (-0.55,-0.05) rectangle (7.55,0.95);

%% ---- Separadores de bloque (líneas verticales) ----
\foreach \x in {0.5,1.5,2.5,3.5,4.5,5.5,6.5}
  \draw[gray!30, thin] (\x,-0.15) -- (\x,3.65);

%% ---- Etiquetas de bloque (arriba) ----
\foreach \x/\bl/\d in {
  0/1/{sem 1--4}, 1/2/{sem 5--8}, 2/3/{sem 9--12},
  3/4/{sem 13--16}, 4/5/{sem 17--20}, 5/6/{sem 21--24}, 6.4/7/{sem 25--30}}{
  \node[font=\scriptsize\bfseries, anchor=south] at (\x,3.60) {B\bl};
  \node[font=\tiny, text=black!50, anchor=south] at (\x,3.42) {\d};
}

%% ---- Etiquetas de stream (izquierda) ----
\node[font=\small\bfseries, text=blue!65,         anchor=east] at (-0.60,3.05) {A};
\node[font=\small\bfseries, text=orange!70!black, anchor=east] at (-0.60,1.75) {B};
\node[font=\small\bfseries, text=green!55!black,  anchor=east] at (-0.60,0.45) {C};

%% ---- Stream A ----
\node[nA] (A1) at (0,   3.05) {A1};
\node[nA] (A2) at (1,   3.05) {A2};
\node[nA] (A3) at (2,   3.05) {A3};
\node[nA] (A4) at (3,   3.05) {A4};
\node[nA] (A5) at (4,   3.05) {A5};
\node[nA] (A6) at (5,   3.05) {A6};
\node[nA] (A7) at (6.4, 3.05) {A7\\Paper};

%% ---- Stream B ----
\node[nB] (B1) at (0,   1.75) {B1};
\node[nH] (B2) at (1,   1.75) {\textbf{B2}\\fab PCB};
\node[nB] (B3) at (2,   1.75) {B3};
\node[nB] (B4) at (3,   1.75) {B4};
\node[nB] (B5) at (4,   1.75) {B5};
\node[nB] (B6) at (5,   1.75) {B6\\panel real};
\node[nB] (B7) at (6.4, 1.75) {B7};

%% ---- Stream C ----
\node[nC] (C1) at (0,   0.45) {C1};
\node[nC] (C2) at (1,   0.45) {C2};
\node[nC] (C3) at (2,   0.45) {C3};
\node[nH] (C4) at (3,   0.45) {\textbf{C4}\\HIL E2E};
\node[nS] (C5) at (4,   0.45) {C5\\stretch};
\node[nS] (C6) at (5,   0.45) {C6\\stretch};
\node[nC] (C7) at (6.4, 0.45) {C7\\TF=7};

%% ---- Flechas dentro de cada stream ----
\foreach \u/\v in {A1/A2,A2/A3,A3/A4,A4/A5,A5/A6,A6/A7}
  \draw[aA] (\u) -- (\v);
\foreach \u/\v in {B1/B2,B2/B3,B3/B4,B4/B5,B5/B6,B6/B7}
  \draw[aB] (\u) -- (\v);
\foreach \u/\v in {C1/C2,C2/C3,C3/C4}
  \draw[aC] (\u) -- (\v);
%% C7 depende de C4 (flecha saltando bloques 5-6)
\draw[aC, dashed] (C4) to[out=0,in=180] (C7);
%% C5/C6 son opcionales
\draw[aC, opacity=0.35] (C4) -- (C5);
\draw[aC, opacity=0.35] (C5) -- (C6);

%% ---- Acoples VERTICALES entre streams ----
%% A2->C2: definición SPI (teal)
\draw[cross] (A2.south) -- (C2.north)
  node[font=\tiny, midway, right=1pt, text=teal!60!black] {SPI};

%% B3->C3: PCB lista (teal)
\draw[cross] (B3.south) -- (C3.north)
  node[font=\tiny, midway, right=1pt, text=teal!60!black] {PCB};

%% B4->C4: convergencia HIL
\draw[cross]  (B4.south) -- (C4.north)
  node[font=\tiny, midway, right=1pt, text=teal!60!black] {medición};

%% C4->A4: resultados HIL al harness
\draw[crossM] (C4.north) -- (A4.south)
  node[font=\tiny, midway, right=1pt, text=magenta!60!black] {HIL$\to$harness};

%% B7->A7: convergencia paper (B7 requiere B6 requiere HIL)
\draw[cross]  (B7.north) to[out=90,in=-80] (A7.south east);

%% ---- Leyenda ----
\node[anchor=north west, font=\scriptsize, draw=black!25, rounded corners=2pt,
      inner sep=5pt, fill=white] at (-0.6,-0.25) {%
  \begin{tabular}{@{}ll@{}}
    \tikz\fill[colorHard,draw=red!70,line width=1.5pt](0,0)rectangle(0.45,0.25); &
      Hito duro (TF\,=\,0, bloqueante)\\[2pt]
    \tikz\fill[colorB!35,draw=colorB!60,dashed,line width=0.8pt](0,0)rectangle(0.45,0.25); &
      Objetivo extendido (stretch, no bloquea)\\[2pt]
    \tikz\draw[teal!60!black,dashed,line width=1.2pt,->](0,0.12)--(0.7,0.12); &
      Acople entre streams (SPI, PCB, medición)\\[2pt]
    \tikz\draw[magenta!60!black,dashed,line width=1.2pt,->](0,0.12)--(0.7,0.12); &
      Transferencia A$\to$C (HIL al harness, algoritmo)\\
  \end{tabular}};

\end{tikzpicture}%
}
\end{center}

---

## 5. Diagrama de Hitos

Los hitos se espacian **$\approx$ 1 mes** desde mayo hasta agosto, y luego **$\approx$ 3 semanas** hasta la defensa.

\begin{center}
\resizebox{\linewidth}{!}{%
\begin{tikzpicture}[
  x=2.1cm, y=1cm,
  harrow/.style={-{Stealth[length=3mm]}, thick, black!55},
  mhard/.style={circle, draw=red!65, fill=colorHard,
                minimum size=0.72cm, font=\scriptsize\bfseries, inner sep=1pt},
  msoft/.style={circle, draw=colorMile!70, fill=colorMile!20,
                minimum size=0.62cm, font=\scriptsize, inner sep=1pt},
  mnow/.style={circle, draw=orange!85, fill=colorHoy,
               minimum size=0.62cm, font=\scriptsize\bfseries, inner sep=1pt},
  lup/.style={font=\scriptsize, anchor=south, align=center, text width=2.8cm},
  ldown/.style={font=\scriptsize, anchor=north, align=center, text width=2.8cm},
  date/.style={font=\tiny\itshape, text=black!45}
]

%% Bandas de período (al fondo, antes de nodos y línea)
\fill[colorHoy!25, opacity=0.5] (-0.3,-2.8) rectangle (3.2, 3.2);
\fill[colorC!18, opacity=0.5] (3.2,-2.8) rectangle (8.9, 3.2);

%% Línea de tiempo
\draw[harrow, line width=1.5pt] (-0.3,0) -- (8.9,0);

%% Marcas verticales
\foreach \x in {0,1,2,3,4,5,6.5,8}
  \draw[thick, black!40] (\x,-0.18) -- (\x,0.18);

%% M0 — HOY
\node[mnow] (M0) at (0, 0.9) {M0};
\node[lup] at (0, 2.0) {\textbf{[HOY]}\\PR esquemático v1};
\node[date, anchor=north] at (0,-0.3) {24 may};
\draw[thin, black!35] (M0) -- (0,0.18);

%% M1 — PCB a fab
\node[mhard] (M1) at (1,-0.9) {M1};
\node[ldown] at (1,-2.0) {\textbf{PCB a fabricación}\\(hito duro)};
\node[date, anchor=south] at (1,0.3) {14 jun};
\draw[thin, red!55] (M1) -- (1,-0.18);

%% M2 — Placa lista
\node[msoft] (M2) at (2, 0.9) {M2};
\node[lup] at (2, 2.0) {PCB ensamblada\\y calibrada};
\node[date, anchor=north] at (2,-0.3) {12 jul};
\draw[thin, black!35] (M2) -- (2,0.18);

%% M3 — HIL E2E
\node[mhard] (M3) at (3,-0.9) {M3};
\node[ldown] at (3,-2.0) {\textbf{HIL extremo\\a extremo}\\(hito duro)};
\node[date, anchor=south] at (3,0.3) {24 ago};
\draw[thin, red!55] (M3) -- (3,-0.18);

%% M4 — Global-MPPT
\node[msoft] (M4) at (4, 0.9) {M4};
\node[lup] at (4, 2.0) {Global-MPPT\\validado (sim+HIL)};
\node[date, anchor=north] at (4,-0.3) {14 sep};
\draw[thin, black!35] (M4) -- (4,0.18);

%% M5 — Ensayo con panel real
\node[mhard] (M5) at (5,-0.9) {M5};
\node[ldown] at (5,-2.0) {\textbf{Ensayo con\\panel real}\\(hito duro)};
\node[date, anchor=south] at (5,0.3) {19 oct};
\draw[thin, red!55] (M5) -- (5,-0.18);

%% M6 — Paper borrador
\node[msoft] (M6) at (6.5, 0.9) {M6};
\node[lup] at (6.5, 2.0) {Paper borrador\\completo};
\node[date, anchor=north] at (6.5,-0.3) {9 nov};
\draw[thin, black!35] (M6) -- (6.5,0.18);

%% M7 — Defensa
\node[mhard] (M7) at (8,-0.9) {M7};
\node[ldown] at (8,-2.0) {\textbf{Defensa}};
\node[date, anchor=south] at (8,0.3) {30 nov};
\draw[thin, red!55] (M7) -- (8,-0.18);

%% Etiquetas de banda (encima del fondo, debajo de los hitos)
\node[font=\tiny\bfseries, text=orange!60!black, anchor=south] at (1.45, 2.95)
  {Mayo–Agosto ($\approx$ mensual)};
\node[font=\tiny\bfseries, text=green!50!black, anchor=south] at (6.05, 2.95)
  {Sep–Nov ($\approx$ 3 semanas)};

%% Leyenda (debajo de todas las etiquetas de hitos)
\node[anchor=north west, font=\scriptsize, draw=black!25, rounded corners=2pt,
      inner sep=5pt, fill=white] at (-0.3,-3.2) {%
  \begin{tabular}{@{}ll@{}}
    \tikz\node[mhard, minimum size=0.5cm]{}; & Hito duro (bloquea el alcance si se incumple)\\[3pt]
    \tikz\node[msoft, minimum size=0.5cm]{}; & Hito de verificación interna\\[3pt]
    \tikz\node[mnow,  minimum size=0.5cm]{}; & Posición actual (hoy)\\
  \end{tabular}};

\end{tikzpicture}%
}
\end{center}

| Hito | Fecha est. | Descripción | Condición de cierre |
|------|-----------|-------------|---------------------|
| M0 | 24 may 2026 | [HOY] PR del esquemático v1 | Esquemático completo en KiCad, revisado por el equipo |
| **M1** | **14 jun 2026** | **PCB a fabricación** | Gerbers enviados al fab, confirmación de pedido recibida |
| M2 | 12 jul 2026 | PCB ensamblada y calibrada | ADC calibrado; placa alimenta correctamente; enlace SPI vivo |
| **M3** | **24 ago 2026** | **HIL extremo a extremo** | Algoritmo Python corre en lazo cerrado sobre hardware real |
| M4 | 14 sep 2026 | Global-MPPT validado | Global-MPPT en harness; figuras del paper generadas |
| **M5** | **19 oct 2026** | **Ensayo con panel real** | B6 completa: sistema HIL corriendo bajo irradiancia variable en exterior |
| M6 | 9 nov 2026 | Paper borrador completo | Todos los capítulos redactados con figuras incluidas |
| **M7** | **30 nov 2026** | **Defensa** | Presentación ante el tribunal |

**Resumen.** El proyecto opera sin margen de seguridad global (TF = 0 en el 90 % de las actividades). El **hito más urgente es M1 (PCB a fabricación, 14 de junio)**: los fabricantes de PCB tienen tiempos de entrega de 2–3 semanas, por lo que el pedido debe emitirse esta semana. Se recomienda mantener una placa de evaluación comercial como respaldo para no bloquear el stream de firmware si el PCB propio se atrasa. Se puede continuar con el desarrollo utilizando una Raspberry Pi 4/5 y una Raspberry Pi Pico, pero no se pueden probar la abstracción de HW.
