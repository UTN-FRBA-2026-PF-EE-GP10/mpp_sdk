---
title: "Análisis de Riesgos"
subtitle: "Tesis de Ingeniería Electrónica"
author: "Grupo 10"
date: "3 de junio de 2026"
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
  - \usepackage{booktabs}
  - \usepackage{longtable}
  - \usepackage{array}
  - \PassOptionsToPackage{table}{xcolor}
  - \usepackage{colortbl}
  - \usepackage{titling}
  - \pretitle{\begin{center}\includegraphics[width=3.2cm]{../logo_UTN.pdf}\\[1em]\LARGE}
  - \posttitle{\par\end{center}\vskip 0.5em}
---

## 1. Contexto

El presente análisis de riesgos se elabora al cierre del **Bloque 1 (Fundación)**, completado en
la semana 4 de 30 del cronograma del proyecto `mpp-sdk`. El siguiente hito duro es el **Hito 1 —
PCB a fabricación** (fin de semana 6), cuyo atraso cascadea directamente sobre los streams B
(banco de pruebas) y C (firmware embebido), desplazando en consecuencia el Hito 2 (HIL extremo a
extremo, semana 16).

En el stream de firmware, el Bloque 1 cerró con un scaffolding funcional de SPI slave implementado
con el bloque PIO del RP2040 (`firmware/src/spi_slave_pio.rs`) y la contraparte Python
(`mpp_sdk/io/spi_mcu.py`). El firmware está escrito en Rust, elección que no estaba contemplada
en el plan original (que presuponía C con el Pico SDK). Este cambio ya es un hecho consumado y
debe ser incorporado explícitamente en el análisis de riesgos.

En el stream de hardware, las decisiones críticas de componentes siguen abiertas a dos semanas
del hito de fabricación: el tipo de transistor de potencia (MOSFET), el gate driver asociado, el
sensor de corriente (INA226 vs. shunt más amplificador de instrumentación) y la frecuencia de
conmutación del convertidor SEPIC. Estas cuatro variables deben cerrarse antes de que el diseñador
de PCB pueda enrutar con criterio de integridad de señal, lo que convierte al proceso de decisión
en sí mismo en un riesgo de cronograma.

El análisis adopta el marco estándar de gestión de riesgos: identificación, clasificación,
cuantificación probabilidad × impacto, y definición de planes de acción con responsable y fecha
límite. Las escalas y criterios se definen en la sección 3.

---

## 2. Riesgos identificados

Se identifican catorce riesgos agrupados en cinco categorías. La tabla siguiente provee la ficha de
identificación; la cuantificación y los planes de acción se desarrollan en las secciones
posteriores.

\vspace{0.5em}

\renewcommand{\arraystretch}{1.6}
\begin{longtable}{>{\bfseries}p{0.8cm} p{2.4cm} p{6.2cm} p{3.8cm}}
\toprule
\textbf{ID} & \textbf{Categoría} & \textbf{Descripción} & \textbf{Origen} \\
\midrule
\endhead
\midrule
\endfoot
\bottomrule
\endlastfoot

R01 & Cronograma &
Atraso en cierre de decisiones de hardware (gate driver, sensor de corriente, frecuencia de
conmutación) impide enrutar la PCB antes del hito de fabricación (semana 6). &
Decisiones abiertas a semana 5; variables interrelacionadas sin responsable único. \\
\midrule

R02 & Hardware &
El MOSFET seleccionado, o el gate driver asociado, tienen tiempo de entrega
(\textit{lead time}) superior a 3 semanas, retrasando el ensamblado y la calibración. &
Mercado de componentes de potencia; stock limitado en distribuidores locales. \\
\midrule

R03 & Hardware &
La topología SEPIC no cumple las especificaciones de rizado de corriente o tensión en el
rango de irradiancia de trabajo, obligando a rediseñar el esquemático tras la fabricación. &
Brecha entre simulación LTspice (componentes ideales) y comportamiento real de inductores
y capacitores de alta frecuencia. \\
\midrule

R04 & Hardware &
El layout de la PCB introduce acoples parásitos (inductancias de pista, capacitancias de
plano) que desestabilizan el lazo de control a la frecuencia de conmutación elegida. &
Sin experiencia previa en PCB de potencia a alta frecuencia; sin revisión externa del
layout. \\
\midrule

R05 & Firmware &
El cambio de C a Rust en el firmware del RP2040 incrementa la curva de aprendizaje y
reduce la disponibilidad de ejemplos de referencia en el ecosistema Pico. &
Decisión tomada en el Bloque 1 sin evaluación formal de impacto en cronograma. \\
\midrule

R06 & Firmware &
La programación del bloque PIO del RP2040 para SPI slave puede presentar errores sutiles
de temporización no detectables sin hardware real, bloqueando la integración HIL. &
Complejidad del modelo PIO (máquina de estados, instrucciones limitadas); depuración en
Rust menos madura que en C. \\
\midrule

R07 & Firmware &
El algoritmo MPPT final no entra en el presupuesto del RP2040
($\le 16\,\text{KB}$ flash, $\le 4\,\text{KB}$ RAM, $\le 1\,\text{ms}$ por paso),
comprometiendo la contribución embebida del paper. &
Huella de memoria y latencia de los algoritmos avanzados no evaluada aún en el target
real. \\
\midrule

R08 & Integración &
La brecha entre el modelo de simulación y el sistema real supera la tolerancia aceptable
($> 5\%$ de error en eficiencia de seguimiento), invalidando las comparaciones del paper. &
Modelo ideal sin pérdidas de conmutación, sin resistencias parásitas de inductores ni
variación de temperatura de junction. \\
\midrule

R09 & Integración &
El protocolo SPI entre la Raspberry Pi 5 (maestro Python) y el RP2040 (esclavo Rust/PIO)
introduce latencias variables o pérdida de tramas que corrompen el lazo HIL. &
Stacks heterogéneos (CPython + \texttt{spidev} vs.\ Rust bare-metal); sincronización
dependiente de temporizadores de ambos extremos. \\
\midrule

R10 & Cronograma &
Caída de disponibilidad de un integrante en el camino crítico durante los Bloques 3 o 4,
cuando convergen los tres streams. &
Equipo de tres personas, 6\,h/semana nominales, sin redundancia de conocimiento en
hardware de potencia ni en firmware embebido. \\
\midrule

R11 & Cronograma &
El hito HIL extremo a extremo (semana 16) no se alcanza por acumulación de atrasos en los
streams B y C, forzando un paper de contribución solo-simulación. &
Cadena secuencial: PCB $\to$ ensamblado $\to$ calibración $\to$ SPI $\to$ HIL. Cualquier
nodo bloquea el siguiente. \\
\midrule

R13 & Académico &
Una publicación concurrente (\textit{scooping}) presenta resultados similares sobre
algoritmos MPPT embebidos en microcontroladores de bajo costo antes de la defensa. &
Área activa de investigación; el enfoque (Python SDK + HIL en RP2040) es reproducible con
equipamiento accesible. \\
\midrule

R14 & Externo &
El RP2040 presenta erratas conocidas en el ADC que requieren workarounds en el firmware;
pueden aparecer incompatibilidades adicionales con el ecosistema Rust. &
Erratas documentadas (ADC); ecosystem Rust para RP2040 más reciente que el SDK en C. \\
\midrule

R15 & Externo &
El fabricante de PCB rechaza el diseño por DRC o extiende el plazo de entrega, retrasando
el inicio del Bloque 3. &
Dependencia de proveedor externo sin contrato formal; experiencia limitada del equipo con
los DRC del fabricante. \\

\end{longtable}
\renewcommand{\arraystretch}{1.0}

---

## 3. Matriz de probabilidad e impacto

### 3.1 Escala y criterios

Probabilidad e impacto se califican de 1 (mínimo) a 5 (máximo). El score $S = P \times I$
determina el nivel: $S \le 3$ Bajo; $4$--$7$ Medio; $8$--$14$ Alto; $S \ge 15$ Crítico.
Impacto 5 corresponde a pérdida del HIL o caída del paper a solo-simulación; probabilidad 5
indica materialización esperada sin acción activa.

\vspace{0.5em}

### 3.2 Tabla de puntuación

\vspace{0.5em}

\renewcommand{\arraystretch}{1.4}
\begin{tabular}{>{\bfseries}p{0.8cm} p{3.5cm} >{\centering}p{2.2cm} >{\centering}p{1.8cm} >{\centering}p{1.5cm} >{\centering\arraybackslash}p{2.2cm}}
\toprule
\textbf{ID} & \textbf{Descripción breve} & \textbf{Probabilidad (1--5)} & \textbf{Impacto (1--5)} &
\textbf{Score} & \textbf{Nivel} \\
\midrule
R01 & Decisiones HW abiertas a sem. 5 & 4 & 5 & 20 & \cellcolor{red!30}Crítico \\
R02 & Lead time de componentes        & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R03 & SEPIC no cumple spec en real    & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R04 & Parásitos de PCB / inestabilidad & 3 & 3 & 9 & \cellcolor{orange!30}Alto \\
R05 & Curva de aprendizaje Rust/Pico  & 4 & 3 & 12 & \cellcolor{orange!30}Alto \\
R06 & Bug temporización PIO SPI slave & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R07 & Algoritmo no entra en MCU       & 3 & 5 & 15 & \cellcolor{red!30}Crítico \\
R08 & Brecha simulación-realidad      & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R09 & Latencia/pérdida en SPI HIL     & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R10 & Caída de integrante clave       & 2 & 5 & 10 & \cellcolor{orange!30}Alto \\
R11 & Hito HIL no alcanzado sem. 16   & 4 & 5 & 20 & \cellcolor{red!30}Crítico \\
R13 & Scooping por publicación concurrente & 2 & 3 & 6 & \cellcolor{yellow!20}Medio \\
R14 & Errata ADC en RP2040            & 2 & 4 & 8  & \cellcolor{orange!30}Alto \\
R15 & Fabricante PCB rechaza diseño   & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
\bottomrule
\end{tabular}
\renewcommand{\arraystretch}{1.0}

\vspace{1em}

### 3.3 Matriz visual 5×5

La tabla siguiente muestra la distribución de riesgos en el espacio probabilidad--impacto. Las
filas representan el impacto (5 = máximo en la fila superior, 1 = mínimo en la inferior); las
columnas representan la probabilidad (1 = mínimo a la izquierda, 5 = máximo a la derecha). Los
identificadores de riesgo aparecen en la celda correspondiente a sus valores asignados. El
color de cada celda refleja el nivel de riesgo agregado según los umbrales definidos en §3.1.

\vspace{0.5em}

\renewcommand{\arraystretch}{2.0}
\begin{tabular}{>{\bfseries\centering}p{1.0cm}
                >{\centering}p{2.2cm}
                >{\centering}p{2.2cm}
                >{\centering}p{2.2cm}
                >{\centering}p{2.2cm}
                >{\centering\arraybackslash}p{2.2cm}}
\toprule
\textbf{I \textbackslash{} P} & \textbf{1} & \textbf{2} & \textbf{3} & \textbf{4} & \textbf{5} \\
\midrule
\textbf{5} &
  \cellcolor{yellow!20} &
  \cellcolor{orange!30}R10 &
  \cellcolor{red!30}R07 &
  \cellcolor{red!30}R01, R11 &
  \cellcolor{red!30} \\
\textbf{4} &
  \cellcolor{yellow!20} &
  \cellcolor{orange!30}R14 &
  \cellcolor{orange!30}R02, R03, R06, R08, R09, R15 &
  \cellcolor{red!30} &
  \cellcolor{red!30} \\
\textbf{3} &
  \cellcolor{green!20} &
  \cellcolor{yellow!20}R13 &
  \cellcolor{orange!30}R04 &
  \cellcolor{orange!30}R05 &
  \cellcolor{red!30} \\
\textbf{2} &
  \cellcolor{green!20} &
  \cellcolor{green!20} &
  \cellcolor{yellow!20} &
  \cellcolor{yellow!20} &
  \cellcolor{orange!30} \\
\textbf{1} &
  \cellcolor{green!20} &
  \cellcolor{green!20} &
  \cellcolor{green!20} &
  \cellcolor{yellow!20} &
  \cellcolor{yellow!20} \\
\bottomrule
\end{tabular}
\renewcommand{\arraystretch}{1.0}

\vspace{0.5em}

---

## 4. Análisis de riesgos críticos

### 4.1 R01 — Decisiones de hardware abiertas (Score 20 — Crítico)

Al cierre del Bloque 1, el gate driver del MOSFET, el sensor de corriente y la frecuencia de
conmutación permanecen sin definir. Estas variables son interdependientes: la frecuencia
determina las pérdidas en el transistor y condiciona el gate driver; el sensor define el ruteo
de la PCB. Si no se cierran antes del fin de la semana 5, el Gerber no puede enviarse a tiempo
(el fabricante requiere 7--10 días hábiles), lo que desplaza en cascada el inicio del Bloque 3
y pone en riesgo el Hito 2 (HIL, semana 16). La acción más efectiva no es técnica sino
organizativa: convocar una sesión de trabajo con agenda y BOM como entregable concreto.

### 4.2 R11 — Hito HIL no alcanzado en semana 16 (Score 20 — Crítico)

El HIL es el hito que convierte el trabajo en un demostrador físico validado; sin él, el paper
cae a contribución solo-simulación. La probabilidad (P = 4) surge de la cadena secuencial que lo
precede: PCB fabricada $\to$ ensamblado $\to$ calibración $\to$ integración SPI $\to$ lazo HIL.
Cada eslabón tiene su propio riesgo (R01, R02, R04, R06, R09), y la falla en cualquiera bloquea
el siguiente. La herramienta de control más efectiva es definir un hito intermedio en semana 12
(PCB calibrada, SPI validado punto a punto) que permita activar el plan de contingencia con
margen suficiente.

### 4.3 R07 — Algoritmo MPPT no entra en el presupuesto del RP2040 (Score 15 — Crítico)

El presupuesto de diseño embebido es $\le 16\,\text{KB}$ flash, $\le 4\,\text{KB}$ RAM,
$\le 1\,\text{ms}$ por paso. Estas cifras son holgadas para P\&O simple, pero los algoritmos
avanzados (lógica difusa, PSO) requieren tablas de membresía o estado de múltiples partículas
que en Rust \texttt{no\_std} deben ser estructuras estáticas de tamaño fijo, determinado en
tiempo de compilación. Si el algoritmo objetivo no cabe, el MCU solo puede correr P\&O, que es
la línea de base y no el resultado diferenciador del paper. La mitigación es ejecutar un
benchmark de recursos (\texttt{cargo size} + SysTick) en el RP2040 real en cuanto el hardware
esté disponible, sin esperar la integración completa del lazo.

---

## 5. Plan de acción

Para cada riesgo con nivel Crítico o Alto se define una estrategia de respuesta, acciones
concretas, el responsable del stream (A = SDK/integración, B = Hardware/PCB, C = Firmware), la
fecha límite y el indicador que confirma que la acción fue exitosa. Los riesgos de nivel Medio
(R13) y Bajo se aceptan sin acción activa en esta etapa del proyecto.

\vspace{0.5em}

\begin{longtable}{>{\bfseries}p{0.7cm} p{1.8cm} p{5.0cm} >{\centering}p{0.9cm} p{1.4cm} p{2.7cm}}
\toprule
\textbf{ID} & \textbf{Estrategia} & \textbf{Acciones concretas} & \textbf{Resp.} &
\textbf{Fecha lím.} & \textbf{Indicador de éxito} \\
\midrule
\endhead
\bottomrule
\endfoot

R01 & Evitar &
Convocar reunión de decisión técnica antes del fin de la sem. 5; cerrar BOM completa en
una sesión (gate driver, sensor de corriente, frecuencia de conmutación). &
B & Sem. 5 &
BOM completa en KiCad con todos los valores definidos. \\[8pt]

R02 & Mitigar &
Verificar stock y lead time en Mouser/Digi-Key/LCSC para los candidatos; realizar el pedido
el mismo día que se aprueba el esquemático. &
B & Sem. 5 &
Pedido confirmado con entrega $\le 5$ días hábiles. \\[8pt]

R03 & Mitigar &
Simular el SEPIC en LTspice con modelos reales (ESR de capacitores, DCR de inductores);
documentar criterios de aceptación (rizado $< 2\%$, eficiencia $> 85\%$). &
B & Sem. 6 &
Reporte LTspice con parámetros reales adjunto al PR de fabricación. \\[8pt]

R04 & Mitigar &
Seguir guías de layout de potencia (loop de conmutación mínimo, plano de retorno limpio);
completar checklist de integridad de señal antes de exportar Gerbers. &
B & Sem. 6 &
Checklist completado y documentado en el PR. \\[8pt]

R05 & Aceptar &
Completar el scaffolding ADC + PWM + SPI en un único binario funcional; documentar la
arquitectura Rust (crates, linker script, probe-rs) en el repositorio. &
C & Sem. 7 &
Binario con ADC + PWM + SPI corriendo en el RP2040 real. \\[8pt]

R06 & Mitigar &
Usar el segundo núcleo del RP2040 como generador de reloj SPI simulado para validar el PIO
sin hardware externo; prueba de estrés de 10.000 transacciones al tener hardware (sem. 9). &
C & Sem. 9 &
10.000 transacciones SPI sin errores de framing. \\[8pt]

R07 & Mitigar &
Medir huella de flash/RAM con \texttt{cargo size} y latencia con SysTick en el Bloque 4;
si excede el presupuesto, definir versión reducida y documentar el trade-off en el paper. &
C + A & Sem. 16 &
Algoritmo en RP2040: flash $\le 16$ KB, RAM $\le 4$ KB, paso $\le 1$ ms. \\[8pt]

R08 & Mitigar &
Incorporar $R_{ds(on)}$ y DCR del inductor al modelo de simulación; definir tolerancia formal
de $< 5\%$ de error en eficiencia de seguimiento entre simulación y banco real. &
A + B & Sem. 14 &
Tabla comparativa sim vs.\ real con error relativo en el draft del paper. \\[8pt]

R09 & Mitigar &
Diseñar trama SPI de longitud fija con checksum CRC-8; implementar re-sincronización en el
esclavo; limitar la frecuencia del lazo HIL a 1 kHz inicialmente. &
A + C & Sem. 13 &
1000 ciclos HIL sin pérdida de trama; latencia $< 1$ ms. \\[8pt]

R10 & Mitigar &
Documentar setup de herramientas y decisiones de diseño en el repositorio; definir plan de
contingencia si un integrante del camino crítico cae más de 2 semanas. &
Todos & Sem. 8 &
Documentación de setup completa en el repositorio. \\[8pt]

R11 & Mitigar &
Definir hito intermedio en sem. 12 (PCB calibrada, SPI validado punto a punto); si no se
alcanza, activar modo degradado: paper solo-simulación con arquitectura HIL documentada. &
Todos & Sem. 12 &
Medición de V/I real desde Python sobre el hardware físico. \\[8pt]

R14 & Mitigar &
Revisar erratas del RP2040 antes de diseñar el firmware de ADC; implementar el workaround
(evitar canal flotante adyacente) desde el inicio del desarrollo. &
C & Sem. 5 &
Código de ADC con workaround implementado y comentado. \\[8pt]

R15 & Evitar &
Ejecutar el DRC del fabricante sobre el diseño KiCad antes de exportar Gerbers; tener
identificado un segundo proveedor de respaldo. &
B & Sem. 6 &
DRC sin errores; pedido enviado con plazo $\le 10$ días hábiles confirmado. \\[8pt]

\end{longtable}

---

## 6. Conclusiones

El análisis identifica tres riesgos críticos (R01, R07, R11) que comparten una estructura de
cascada: la no-acción en las próximas dos semanas se amplifica directamente en el cronograma.
R01 es el de mayor urgencia: las decisiones de componentes (gate driver, sensor de corriente,
frecuencia de conmutación) deben cerrarse antes del fin de la semana 5 para que la PCB pueda
enviarse a fabricación en la semana 6. Un atraso de tres días en este cierre equivale a dos
semanas de desplazamiento en el inicio del Bloque 3, comprometiendo la cadena entera que
desemboca en el Hito 2 (HIL, semana 16).

La adopción de Rust en el firmware no es un riesgo bloqueante — el scaffolding de SPI slave con
PIO entregado en el Bloque 1 lo demuestra — pero sí introduce una penalidad de tiempo en tareas
que no fueron presupuestadas en C. El riesgo R07 (algoritmo que no entra en el MCU) no puede
evaluarse hasta tener el hardware disponible; la acción de mitigación es ejecutar un benchmark
de recursos (flash, RAM, latencia por paso) con el algoritmo más complejo tan pronto como el
Bloque 3 lo permita, sin esperar la integración completa del lazo.

El hito HIL de la semana 16 es el discriminador académico del proyecto: define si el trabajo
presenta validación experimental o simulación únicamente. La definición de un hito intermedio en
semana 12 (PCB calibrada, SPI validado punto a punto) es el mecanismo de alerta temprana para
detectar desvíos con margen suficiente de reacción.
