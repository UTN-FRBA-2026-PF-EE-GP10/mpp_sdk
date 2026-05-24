---
documentclass: IEEEtran
classoption:
  - journal
  - twocolumn
title: >-
  Framework para Comparación y Desarrollo de Algoritmos MPPT
author: "\\vspace{-2em}"
date: 2026
abstract: |
  Este trabajo aborda la evaluación y validación de algoritmos de búsqueda del
  punto de máxima potencia (MPP) en sistemas fotovoltaicos, junto con el
  desarrollo de un algoritmo propio orientado a la simplicidad y eficiencia.
  Se propone un enfoque que integra simulación y ejecución en hardware real
  mediante una capa de abstracción común. El mismo código de control opera
  sin modificaciones sobre un modelo de panel simulado o sobre un convertidor
  SEPIC real, intercambiando únicamente el adaptador subyacente. Como caso de
  estudio, se diseña e implementa un algoritmo orientado a la ejecución en
  microcontroladores de recursos limitados, demostrando la facilidad de
  desarrollo e integración del enfoque.
bibliography: references.bib
csl: ieee-jestpe.csl
header-includes:
  - \usepackage[spanish]{babel}
  - \usepackage{graphicx}
  - \IEEEoverridecommandlockouts
  - \IEEEspecialpapernotice{\includegraphics[width=2.8cm]{../logo_UTN.pdf}}
  - |
    \makeatletter
    \AtBeginDocument{%
      \let\savedtitle\@title
      \def\@title{\savedtitle\\[4pt]{\normalsize\itshape Tesis Final de Grado --- Ingeniería Electrónica}}%
      \def\@author{%
        \IEEEauthorblockN{Borello,~Federico \and Falabella,~Juan \and Pirotta,~Diego~Nahuel}\\[4pt]%
        \IEEEauthorblockA{Universidad Tecnológica Nacional --- Facultad Regional Buenos Aires}%
      }%
    }
    \makeatother
---

```{=latex}
\begin{IEEEkeywords}
MPPT, fotovoltaico, simulación, abstracción hardware, microcontrolador
\end{IEEEkeywords}
```

# Introducción

Los sistemas fotovoltaicos (FV) requieren algoritmos de seguimiento del punto
de máxima potencia (MPPT, del inglés *Maximum Power Point Tracking*) para
maximizar la energía extraída del panel bajo condiciones variables de irradiancia
y temperatura [@esram2007comparison]. Entre los métodos más difundidos se
encuentran Perturbar y Observar (P&O) e Incremento de Conductancia (INC), cuya
efectividad y costo computacional varían según la aplicación [@femia2005optimization].

El modelado preciso del panel FV es la base sobre la que se evalúan estos
algoritmos en simulación [@villalva2009comprehensive]. Herramientas como pvlib
permiten reproducir el comportamiento eléctrico de módulos reales con alta
fidelidad [@holmgren2018pvlib], aunque la transición desde la simulación hacia
la validación en hardware frecuentemente implica reescribir lógica de control
o adaptar interfaces, introduciendo fricciones y posibles discrepancias.

# Enfoque Propuesto

El framework separa el algoritmo de control del medio de ejecución mediante
una capa de abstracción de señales. Así, el mismo código corre indistintamente
sobre un modelo de panel simulado con pvlib o sobre un convertidor SEPIC real,
sin requerir modificaciones. El intercambio se reduce a seleccionar la fuente
de datos —simulada o hardware— al momento de inicializar el sistema.

Esto hace posible ajustar y comparar algoritmos en simulación y luego
ejecutarlos directamente en el banco de pruebas, con las mismas métricas
y bajo las mismas condiciones de entrada.

# Algoritmo Propuesto

Como caso de estudio se desarrolla un algoritmo propio con bajo costo
computacional, pensado para correr en microcontroladores de gama baja.
Se busca que su eficiencia de rastreo sea competitiva frente a P&O estándar,
validándolo primero en simulación y luego sobre el hardware real.

# Referencias
