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
  - \usepackage{colortbl}
  - \usepackage[table]{xcolor}
  - \usepackage{titling}
  - \pretitle{\begin{center}\includegraphics[width=3.2cm]{../logo_UTN.pdf}\\[1em]\LARGE}
  - \posttitle{\par\end{center}\vskip 0.5em}
---

## 1. Contexto

El presente análisis de riesgos se elabora al cierre del **Bloque 1 (Fundación)**, semana 4 de 30
del cronograma del proyecto `mpp-sdk`. El momento es particularmente sensible: en exactamente dos
semanas vence el **Hito 1 — PCB a fabricación** (fin de semana 6), que constituye el primer hito
duro del plan y cuyo atraso cascadea directamente sobre los streams B (banco de pruebas) y C
(firmware embebido), desplazando en consecuencia el Hito 2 (HIL extremo a extremo, semana 16).

En el stream de firmware, el repositorio registra avance concreto: la rama
`fborello/pico_fw_scaffolding` incluye un scaffolding funcional de SPI slave implementado con el
bloque PIO del RP2350 (`firmware/src/spi_slave_pio.rs`) y la contraparte Python
(`mpp_sdk/io/spi_mcu.py`). El firmware está escrito en Rust, elección que no estaba contemplada
en el plan original (que presuponía C con el Pico SDK). Este cambio ya es un hecho consumado y
debe ser incorporado explícitamente en el análisis de riesgos.

En el stream de hardware, las decisiones críticas de componentes siguen abiertas a dos semanas
del hito de fabricación: el tipo de transistor de potencia (GaN vs. SiC), el gate driver
asociado, el sensor de corriente (INA226 vs. shunt más amplificador de instrumentación) y la
frecuencia de conmutación del convertidor SEPIC. Estas cuatro variables deben cerrarse antes de
que el diseñador de PCB pueda enrutar con criterio de integridad de señal, lo que convierte al
proceso de decisión en sí mismo en un riesgo de cronograma.

El análisis adopta el marco estándar de gestión de riesgos: identificación, clasificación,
cuantificación probabilidad × impacto, y definición de planes de acción con responsable y fecha
límite. Las escalas y criterios se definen en la sección 3.

---

## 2. Riesgos identificados

Se identifican quince riesgos agrupados en seis categorías. La tabla siguiente provee la ficha de
identificación; la cuantificación y los planes de acción se desarrollan en las secciones
posteriores.

\vspace{0.5em}

\begin{longtable}{>{\bfseries}p{0.8cm} p{2.2cm} p{6.5cm} p{3.8cm}}
\toprule
\textbf{ID} & \textbf{Categoría} & \textbf{Descripción} & \textbf{Origen} \\
\midrule
\endhead
\bottomrule
\endfoot

R01 & Cronograma & Atraso en cierre de decisiones de hardware (FET, gate driver, sensor de
corriente, frecuencia de conmutación) impide enrutar la PCB antes del hito de fabricación
(semana 6). & Decisiones abiertas a semana 4; cuatro variables interrelacionadas sin responsable
único. \\[4pt]

R02 & Hardware & El transistor GaN o SiC seleccionado, o el gate driver asociado, tienen tiempo
de entrega (\textit{lead time}) superior a 3 semanas, retrasando el ensamblado y la calibración. &
Mercado de componentes de potencia de alta frecuencia; discontinuaciones frecuentes y stock
limitado en distribuidores locales. \\[4pt]

R03 & Hardware & La topología SEPIC diseñada no cumple las especificaciones de rizado de
corriente o tensión en el rango de irradiancia de trabajo, lo que obliga a rediseñar el
esquemático tras la fabricación. & Brecha entre simulación en LTspice (componentes ideales) y
comportamiento real de inductores y capacitores de alta frecuencia. \\[4pt]

R04 & Hardware & El layout de la PCB introduce acoples parásitos (inductancias de pista,
capacitancias de plano) que desestabilizan el lazo de control a la frecuencia de conmutación
elegida. & Falta de experiencia previa del equipo en diseño de PCB de potencia a alta
frecuencia; sin revisión externa del layout. \\[4pt]

R05 & Firmware & El cambio no planeado de C a Rust en el firmware del RP2350 incrementa la
curva de aprendizaje y reduce la disponibilidad de ejemplos de referencia para el Pico SDK en
ese lenguaje. & Decisión técnica tomada en el transcurso del Bloque 1 sin evaluación formal de
impacto en cronograma. \\[4pt]

R06 & Firmware & La programación del bloque PIO del RP2350 para SPI slave presenta errores
sutiles de temporización o sincronización que no son detectables sin hardware real, bloqueando
la integración HIL hasta el Bloque 3. & Complejidad inherente al modelo de programación PIO
(máquina de estados con instrucciones limitadas); ecosistema de depuración en Rust menos maduro
que en C. \\[4pt]

R07 & Firmware & El algoritmo MPPT final (fuzzy logic, PSO o variante propia) no entra en el
presupuesto de recursos del RP2350 ($\le 16$ KB de flash, $\le 4$ KB de RAM, $\le 1$ ms por
paso de control), requiriendo simplificación que compromete la contribución al paper. &
Restricción de recursos definida en el plan; los algoritmos avanzados tienen complejidad
computacional y huella de memoria no evaluada empíricamente en el target. \\[4pt]

R08 & Integración & La brecha entre el modelo de simulación (IdealSingleDiode + SEPIC ideal) y
el sistema real supera la tolerancia aceptable ($> 5\%$ de error en eficiencia de seguimiento),
invalidando las comparaciones del paper que combinan resultados simulados y medidos. &
Simplificaciones del modelo: sin pérdidas de conmutación, sin resistencias parásitas de
inductores, sin variación de temperatura de junction. \\[4pt]

R09 & Integración & El protocolo SPI entre la Raspberry Pi 5 (maestro Python) y el RP2350
(esclavo Rust/PIO) introduce latencias variables o pérdida de tramas bajo carga, corrompiendo
el lazo de control HIL en tiempo real. & Mezcla de dos stacks de software heterogéneos (CPython
con \texttt{spidev} y Rust bare-metal); la sincronización depende de temporizadores de ambos
extremos. \\[4pt]

R10 & Cronograma & Caída de disponibilidad de un integrante en el camino crítico (enfermedad,
obligaciones laborales o académicas) durante el Bloque 3 o 4, cuando convergen los tres
streams. & Equipo de tres personas con 6 h/semana nominales y sin redundancia de conocimiento
en hardware de potencia ni en firmware embebido. \\[4pt]

R11 & Cronograma & El hito HIL extremo a extremo (semana 16) no se alcanza por acumulación de
atrasos en los streams B y C, forzando que el paper se entregue como contribución solo
simulación. & Dependencia secuencial: PCB fabricada $\to$ ensamblado $\to$ calibración $\to$
integración SPI $\to$ HIL. Cualquier nodo en la cadena puede bloquear el siguiente. \\[4pt]

R12 & Académico & El tribunal evalúa negativamente el uso de herramientas de IA generativa en
la redacción del paper o en la generación de código, interpretándolo como falta de autoría
genuina. & Regulaciones institucionales en evolución; criterios de evaluación no publicados
explícitamente para trabajos finales que usan asistencia LLM. \\[4pt]

R13 & Académico & Una publicación concurrente (\textit{scooping}) presenta resultados similares
en comparación de algoritmos MPPT embebidos sobre microcontroladores de bajo costo antes de la
defensa, reduciendo la novedad del trabajo. & Área activa de investigación; el enfoque (Python
SDK + HIL en Pico 2) es reproducible con equipamiento de bajo costo, favoreciendo la
competencia académica. \\[4pt]

R14 & Externo & La Raspberry Pi Pico 2 (RP2350) sufre un cambio de revisión de silicio o una
errata crítica que afecta al bloque PIO o al ADC, requiriendo adaptaciones no planificadas en
el firmware. & El RP2350 es un chip relativamente nuevo (2024); la errata RP2350-E9 sobre el
ADC ya es conocida y requiere workarounds específicos. \\[4pt]

R15 & Externo & El proveedor de fabricación de PCB introduce tiempos de entrega más largos de
los esperados o rechaza el diseño por DRC, retrasando el inicio del Bloque 3. & Dependencia de
un proveedor externo sin contrato formal; experiencia limitada del equipo con los DRC del
fabricante específico. \\[4pt]

\end{longtable}

---

## 3. Matriz de probabilidad e impacto

### 3.1 Escala y criterios

La probabilidad y el impacto se evalúan en una escala entera de 1 a 5. La tabla siguiente
define los criterios cualitativos utilizados para la asignación:

\vspace{0.5em}

\begin{tabular}{>{\bfseries}p{1.2cm} p{5.5cm} p{5.5cm}}
\toprule
\textbf{Nivel} & \textbf{Probabilidad} & \textbf{Impacto} \\
\midrule
1 & Muy improbable ($< 10\%$): condición teórica sin evidencia de materialización. &
Mínimo: retraso $< 3$ días o rework de un módulo aislado sin efecto en hitos. \\[4pt]
2 & Improbable ($10\text{--}25\%$): posible en condiciones adversas, con historial
escaso. & Menor: retraso de 1 semana o degradación parcial de una métrica del paper. \\[4pt]
3 & Probable ($25\text{--}50\%$): ocurrencia observada en proyectos similares sin
mitigación activa. & Moderado: retraso de 2--3 semanas o pérdida de un entregable secundario. \\[4pt]
4 & Muy probable ($50\text{--}75\%$): tendencia clara o condición estructural
presente en el proyecto. & Alto: desplazamiento de un hito duro o degradación significativa
del paper. \\[4pt]
5 & Casi seguro ($> 75\%$): materialización esperada si no se actúa. &
Crítico: pérdida del HIL, caída del paper a solo-simulación, o defensa comprometida. \\[4pt]
\bottomrule
\end{tabular}

\vspace{0.5em}

El nivel de riesgo agregado se define por el score $S = P \times I$ según los umbrales:
$S \le 3$ $\to$ Bajo; $4 \le S \le 7$ $\to$ Medio; $8 \le S \le 14$ $\to$ Alto; $S \ge 15$ $\to$ Crítico.

\vspace{0.5em}

### 3.2 Tabla de puntuación

\vspace{0.5em}

\begin{tabular}{>{\bfseries}p{0.8cm} p{3.5cm} >{\centering}p{2.2cm} >{\centering}p{1.8cm} >{\centering}p{1.5cm} >{\centering\arraybackslash}p{2.2cm}}
\toprule
\textbf{ID} & \textbf{Descripción breve} & \textbf{Probabilidad (1--5)} & \textbf{Impacto (1--5)} &
\textbf{Score} & \textbf{Nivel} \\
\midrule
R01 & Decisiones HW abiertas a sem. 4 & 4 & 5 & 20 & \cellcolor{red!30}Crítico \\
R02 & Lead time de componentes & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R03 & SEPIC no cumple spec en real & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R04 & Parásitos de PCB / inestabilidad & 3 & 3 & 9  & \cellcolor{orange!30}Alto \\
R05 & Curva de aprendizaje Rust/Pico & 4 & 3 & 12 & \cellcolor{orange!30}Alto \\
R06 & Bug temporización PIO SPI slave & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R07 & Algoritmo no entra en MCU & 3 & 5 & 15 & \cellcolor{red!30}Crítico \\
R08 & Brecha simulación-realidad & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R09 & Latencia/pérdida en SPI HIL & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
R10 & Caída de integrante clave & 2 & 5 & 10 & \cellcolor{orange!30}Alto \\
R11 & Hito HIL no alcanzado sem. 16 & 4 & 5 & 20 & \cellcolor{red!30}Crítico \\
R12 & Sesgo tribunal ante uso de IA & 3 & 3 & 9  & \cellcolor{orange!30}Alto \\
R13 & Scooping por publicación concurrente & 2 & 3 & 6 & \cellcolor{yellow!20}Medio \\
R14 & Errata crítica en RP2350 & 2 & 4 & 8  & \cellcolor{orange!30}Alto \\
R15 & Fabricante PCB rechaza diseño & 3 & 4 & 12 & \cellcolor{orange!30}Alto \\
\bottomrule
\end{tabular}

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
  \cellcolor{orange!30}R04, R05, R12 &
  \cellcolor{orange!30} &
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

*Nota: R05 tiene P=4, I=3 (Score=12, Alto) y aparece en la fila I=3, columna P=4.*

---

## 4. Análisis detallado de riesgos críticos y altos de mayor score

### 4.1 R01 — Decisiones de hardware abiertas a dos semanas del hito de fabricación (Score 20 — Crítico)

A la fecha de este análisis (semana 4), cuatro variables de diseño del convertidor SEPIC
permanecen sin resolver: el tipo de transistor de potencia (GaN vs. SiC), el circuito integrado
de gate driver asociado, el sensor de corriente (INA226 integrado vs. shunt más amplificador de
instrumentación discreto) y la frecuencia de conmutación objetivo. Estas cuatro variables son
interdependientes: la frecuencia de conmutación determina las pérdidas en el transistor y, por
ende, el criterio de selección entre GaN y SiC; el gate driver se elige en función del transistor
y de la frecuencia; el sensor de corriente define la topología de medición y el ruteo de la PCB
alrededor del punto de medición. Resolver una variable en el orden incorrecto puede requerir
revisar las anteriores.

La probabilidad de materialización es alta (P = 4) porque la dinámica de trabajo en equipo con
disponibilidad limitada (6 h/semana nominales) hace que este tipo de decisiones multi-variable se
postergue de forma natural hasta que se percibe la presión del hito. El impacto es máximo (I = 5)
porque si las decisiones no se cierran antes del fin de la semana 5, el diseñador de PCB no puede
completar el enrutado en tiempo: el tiempo mínimo de fabricación del proveedor es de 7--10 días
hábiles, lo que significa que el archivo Gerber debe enviarse no más tarde del inicio de la semana
6. Un atraso de incluso tres días en el cierre de las decisiones se convierte directamente en un
atraso de dos semanas en la entrega del PCB fabricado, cascadeando al hito HIL de la semana 16.

El riesgo se agrava por la ausencia de un proceso formal de toma de decisiones: no hay una reunión
convocada, no hay criterios de evaluación documentados para la selección del FET y no hay una
persona designada como responsable de decisión final. En la práctica, esto significa que la
decisión puede seguir abierta hasta que alguien perciba la urgencia, con las consecuencias ya
descritas. La acción de mitigación más efectiva en este momento no es técnica sino organizativa:
fijar una sesión de trabajo con agenda y entregable concreto antes de que finalice la semana 4.

### 4.2 R11 — Hito HIL extremo a extremo no alcanzado en semana 16 (Score 20 — Crítico)

El hito de Hardware-in-the-Loop (HIL) en la semana 16 es el segundo hito duro del proyecto y el
más estratégico desde el punto de vista académico: es el que convierte al trabajo de una
contribución de simulación pura en un demostrador físico validado. Si este hito falla, el paper
debe ser reformulado para presentar únicamente resultados de simulación, perdiendo la contribución
experimental que diferencia al trabajo de proyectos previos similares en el mismo campo.

La probabilidad de no alcanzar el hito (P = 4) surge de la cadena de dependencias secuenciales
que lo preceden: PCB fabricada $\to$ ensamblado y soldado $\to$ calibración de la cadena de
medición $\to$ integración del protocolo SPI $\to$ prueba de lazo cerrado HIL. Cada eslabón tiene
su propio riesgo (R01, R02, R03, R04, R06, R09) y el hito HIL es el resultado de que todos ellos
se resuelvan correctamente en secuencia. La probabilidad compuesta de que la cadena completa no
falle en ningún nodo es notablemente menor que la probabilidad de éxito de cada eslabón de forma
individual. Con seis eslabones y probabilidades de fallo individuales de entre el 25 y el 50\%,
la cadena entera es frágil por construcción.

El impacto es máximo (I = 5) y doble: técnico y académico. Técnicamente, sin HIL no hay
validación experimental de los algoritmos en el MCU target, y por tanto no hay datos reales para
la tabla comparativa central del paper. Académicamente, el tribunal espera un demostrador físico
como parte de una tesis de Ingeniería Electrónica: una defensa basada exclusivamente en
simulación tiene un riesgo significativo de recibir observaciones que exijan trabajo adicional
antes de la aprobación, extendiendo el proyecto más allá del horizonte previsto. La definición de
un hito intermedio en semana 12 (PCB calibrada y SPI validado punto a punto sin lazo MPPT) es la
herramienta de monitoreo más efectiva para detectar a tiempo si la cadena está en riesgo.

### 4.3 R07 — Algoritmo MPPT no entra en el presupuesto de recursos del RP2350 (Score 15 — Crítico)

El plan establece como restricción de diseño embebido que el algoritmo MPPT final ocupe como
máximo 16 KB de flash, 4 KB de RAM, y ejecute un paso de control en no más de 1 ms con el RP2350
corriendo a 150 MHz. Estas cifras son generosas para un algoritmo P\&O simple, pero pueden
resultar restrictivas para los algoritmos avanzados que constituyen la contribución principal del
trabajo: lógica difusa (requiere tablas de membresía y un motor de inferencia), PSO (requiere
mantener el estado de múltiples partículas en memoria) o un algoritmo propio con mayor
complejidad estructural.

La probabilidad de materialización (P = 3) es moderada porque no se ha realizado aún ningún
perfilado de recursos en el target real. En simulación Python, los algoritmos corren sin
restricción de memoria o tiempo; la reimplementación en Rust embebido puede revelar que
estructuras de datos que son triviales en Python (diccionarios, listas dinámicas, closures)
requieren un diseño explícito en Rust \texttt{no\_std} que incrementa tanto la complejidad como
el tamaño del binario compilado. El impacto es máximo (I = 5) porque si el algoritmo de mayor
complejidad no puede embeberse, el MCU solo puede correr P\&O, que es la línea de base y no el
resultado novedoso: el paper perdería su contribución embebida principal, que es precisamente el
elemento diferenciador frente a trabajos previos.

El agravante específico del ecosistema Rust en bare-metal es relevante aquí: la librería estándar
de Rust no está disponible en \texttt{no\_std}, lo que elimina colecciones dinámicas y obliga a
estructuras estáticas de tamaño fijo. Un algoritmo PSO con N partículas en Python puede
implementarse con una lista de largo variable; en Rust bare-metal requiere un array estático de N
fijo, con N determinado en tiempo de compilación. La elección de N tiene impacto directo en el
presupuesto de RAM, y la elección de N demasiado conservadora puede limitar la calidad de la
búsqueda del MPP. La acción de mitigación recomendada es construir un benchmark de recursos en
el RP2350 tan pronto como el hardware esté disponible, sin esperar a la integración completa del
lazo de control.

### 4.4 R05 — Curva de aprendizaje Rust en firmware del RP2350 (Score 12 — Alto)

El cambio de lenguaje de firmware de C (Pico SDK estándar) a Rust no fue parte del plan original
y se materializó durante el Bloque 1. Rust es un lenguaje con una curva de aprendizaje
significativamente más pronunciada que C para programación embebida: el modelo de ownership y
borrowing, la ausencia de \texttt{std}, el ecosistema \texttt{embassy} o \texttt{rp-hal} para el
RP2350, y las herramientas de depuración (probe-rs, defmt) requieren una inversión de tiempo que
no fue presupuestada en el cronograma. La buena noticia es que el scaffolding actual de SPI slave
con PIO es evidencia concreta de que el equipo puede avanzar en este ecosistema; el riesgo no es
de bloqueo total sino de velocidad reducida en tareas que se subestiman.

El impacto concreto (I = 3) es que tareas que en C tomarían un día de trabajo pueden tomar tres
o cuatro días en Rust para alguien sin experiencia previa en lenguaje embebido: configurar el
linker script, entender los traits de hal, depurar con probe-rs en lugar de OpenOCD, y aprovechar
el PIO desde Rust (que requiere el crate \texttt{pio} y macros específicas de ensamblador PIO). La
integración completa del lazo de control (ADC + PWM + SPI + algoritmo MPPT) en un solo binario
\texttt{no\_std} es un desafío de mayor complejidad que el scaffolding actual, y puede consumir
tiempo no presupuestado del Bloque 3 si no se gestiona activamente.

### 4.5 R06 — Bug de temporización en el bloque PIO para SPI slave (Score 12 — Alto)

El bloque PIO del RP2350 es una de las características más potentes pero también más complejas del
chip: permite implementar protocolos digitales personalizados con precisión de ciclo de reloj
mediante un conjunto reducido de instrucciones (jmp, wait, in, out, set, mov, push, pull). La
implementación de un SPI slave con PIO requiere gestionar la polaridad de reloj, la fase de
muestreo, el tamaño de palabra y la sincronización con el DMA o las interrupciones del procesador
principal, todo ello en un programa de máximo 32 instrucciones por bloque PIO.

Los errores de temporización en este contexto son difíciles de detectar sin hardware real: en
simulación o con lógica analizadora de software, las interacciones entre el reloj del maestro SPI
(Raspberry Pi 5, ejecutando \texttt{spidev} sobre Linux), los ciclos de respuesta del PIO, y las
interrupciones del sistema operativo del maestro pueden resultar en pérdida de bits o
desincronización de trama que solo aparece bajo condiciones de carga o con ciertos patrones de
datos. El scaffolding actual muestra que la estructura básica está en marcha, pero la validación
completa requiere la integración con el maestro Python y pruebas de estrés que no pueden
realizarse sin el hardware completo ensamblado. La detección tardía de este tipo de bug,
después del Bloque 3, puede consumir tiempo crítico del Bloque 4.

### 4.6 R15 — Rechazo o demora del fabricante de PCB (Score 12 — Alto)

La cadena crítica de los streams B y C comienza en el envío de los archivos Gerber al fabricante
de PCB. Si el fabricante rechaza el diseño por violaciones de las reglas de diseño propias del
proceso de fabricación (anchuras mínimas de pista, separaciones, tamaño mínimo de via, copper
coverage para procesos de 2 capas), o si su tiempo de producción se extiende más allá de lo
previsto (feriados nacionales, falla de equipamiento, alta carga de pedidos), el inicio del Bloque
3 se desplaza directamente. Un rechazo DRC implica un ciclo de corrección más reenvío que puede
consumir entre 3 y 7 días adicionales, mientras que un tiempo de entrega extendido no es
controlable una vez enviado el pedido. La ejecución del DRC del fabricante sobre el diseño KiCad
antes de exportar los Gerbers es la acción de mitigación más efectiva y de menor costo.

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
(1) Convocar reunión de decisión técnica antes del fin de la semana 4.
(2) Documentar criterios de selección FET: pérdidas de conmutación, disponibilidad, costo,
footprint.
(3) Designar a B como responsable de decisión final con capacidad de desempate.
(4) Cerrar todas las decisiones de componentes en una única sesión de trabajo conjunta. &
B & Sem. 5 (día 1) &
Commit en KiCad con BOM completa y todos los valores de componentes definidos. \\[4pt]

R02 & Mitigar &
(1) Antes de cerrar la decisión de FET, verificar stock en Mouser, Digi-Key y LCSC para los
candidatos finalistas.
(2) Seleccionar el componente con stock $\ge 10$ unidades y entrega $\le 5$ días hábiles.
(3) Identificar un componente de respaldo compatible en footprint.
(4) Realizar el pedido el mismo día que se aprueba el esquemático final. &
B & Sem. 5 &
Componente principal y respaldo con stock confirmado; pedido realizado antes del fin de sem. 5. \\[4pt]

R03 & Mitigar &
(1) Completar la simulación LTspice del SEPIC con modelos SPICE de los componentes reales
(incluyendo ESR de capacitores y DCR de inductores).
(2) Definir criterios de aceptación cuantitativos: rizado de tensión $< 2\%$, rizado de
corriente $< 30\%$, eficiencia $> 85\%$ en punto nominal.
(3) Documentar resultados de simulación como adjunto al PR de fabricación. &
B & Sem. 6 &
Reporte LTspice con parámetros reales adjunto al PR de fabricación. \\[4pt]

R04 & Mitigar &
(1) Seguir guías de layout para potencia: planos de ground separados, retorno de corriente de
conmutación en loop mínimo, vias térmicas bajo el FET.
(2) Completar un checklist estándar de integridad de señal antes de exportar Gerbers.
(3) Solicitar revisión del layout a un docente del laboratorio de electrónica de potencia si
es posible antes del envío. &
B & Sem. 6 &
Checklist completado; comentarios de revisión incorporados y documentados en el PR. \\[4pt]

R05 & Aceptar / Mitigar &
(1) Aceptar el cambio a Rust como decisión definitiva y no revertir a C.
(2) Dedicar la semana 5 a completar el scaffolding básico: ADC, PWM y SPI en un único binario
funcional (sin algoritmo MPPT).
(3) Documentar en el repositorio las decisiones de arquitectura Rust (crates, linker script,
probe-rs setup) para reducir fricción futura.
(4) Usar los ejemplos del crate \texttt{rp235x-hal} como referencia canónica. &
C & Sem. 7 &
Binario compilable con ADC + PWM + SPI funcionando en el RP2350 real, verificado con
analizador lógico. \\[4pt]

R06 & Mitigar &
(1) Desarrollar un banco de prueba del PIO usando el segundo núcleo del RP2350 como generador
de reloj SPI maestro simulado, eliminando la dependencia del hardware externo.
(2) Agregar trazas \texttt{defmt} para registrar cada transición relevante de la máquina PIO.
(3) Una vez disponible el hardware (sem. 9+), realizar prueba de estrés: 10.000 transacciones
SPI consecutivas con datos aleatorios y verificar integridad byte a byte. &
C & Sem. 9 &
10.000 transacciones SPI sin errores de framing, resultado documentado en el repositorio. \\[4pt]

R07 & Mitigar &
(1) Implementar el algoritmo más complejo (fuzzy o PSO) en Rust \texttt{no\_std} en el Bloque
4, antes del Bloque 5.
(2) Medir huella de flash y RAM con \texttt{cargo size} y tiempo de ejecución con SysTick antes
de integrar al lazo.
(3) Si el algoritmo excede el presupuesto, definir una versión reducida (N fijo en PSO,
tabla de membresía de resolución reducida en fuzzy) que cumpla las restricciones.
(4) Documentar el trade-off en el paper como análisis de desempeño embebido. &
C + A & Sem. 16 &
Algoritmo corriendo en RP2350 con flash $\le 16$ KB, RAM $\le 4$ KB, paso $\le 1$ ms. \\[4pt]

R08 & Mitigar &
(1) Incorporar al modelo de simulación las pérdidas de conmutación del FET real
($R_{ds(on)}$, $Q_{sw}$ del datasheet) y la DCR del inductor elegido.
(2) Definir una tolerancia de aceptación formal: error $< 5\%$ en eficiencia de seguimiento
entre simulación y medición real.
(3) Si la brecha supera el umbral, reportarla cuantitativamente en el paper como resultado
(la cuantificación del error de modelo es en sí misma una contribución). &
A + B & Sem. 14 &
Tabla comparativa simulación vs. real con error relativo documentado en el draft del paper. \\[4pt]

R09 & Mitigar &
(1) Definir un protocolo SPI con trama de longitud fija y campo de checksum CRC-8 para
detectar corrupción en tiempo real.
(2) Implementar un mecanismo de re-sincronización en el esclavo (reinicio del bloque PIO
tras N bytes sin trama válida).
(3) Limitar la frecuencia de muestreo del lazo HIL a 1 kHz inicialmente y aumentar
gradualmente con medición de latencia. &
A + C & Sem. 13 &
Lazo HIL ejecutando 1000 ciclos de control sin pérdida de trama; latencia máxima $< 1$ ms. \\[4pt]

R10 & Mitigar &
(1) Documentar el conocimiento de hardware de potencia y firmware embebido en el repositorio
(decisiones de diseño, setup de herramientas, procedimiento de calibración).
(2) Establecer plan de contingencia: si B cae más de 2 semanas, A asume revisión del layout
con soporte asíncrono de B.
(3) Mantener el roadmap actualizado con avance real semanal visible para los tres
integrantes. &
Todos & Sem. 8 &
Documentación de setup y procedimientos completa; roadmap actualizado con avance real sem. 8. \\[4pt]

R11 & Mitigar &
(1) Definir hito intermedio en semana 12 (fin del Bloque 3): PCB calibrada y protocolo SPI
validado punto a punto.
(2) Si en semana 12 no se alcanza el hito intermedio, activar plan de contingencia: paper
reformulado como contribución simulación + arquitectura HIL sin resultados experimentales.
(3) Comunicar al director de tesis el estado real del proyecto en semana 12 sin demora. &
Todos & Sem. 12 &
Hito intermedio sem. 12 alcanzado: medición de tensión/corriente real desde Python sobre el
hardware físico. \\[4pt]

R12 & Mitigar &
(1) Documentar explícitamente en el paper el rol de las herramientas LLM: generación de
código auxiliar, revisión de prosa; no generación de resultados ni conclusiones.
(2) Consultar al director de tesis antes de la defensa sobre la política del tribunal.
(3) Preparar una sección metodológica que describa el proceso de verificación de cada
contribución generada con asistencia LLM. &
A & Sem. 20 &
Sección metodológica aprobada por el director; política del tribunal clarificada por escrito. \\[4pt]

R14 & Mitigar &
(1) Revisar la lista completa de erratas del RP2350 (documento oficial Raspberry Pi) antes
de diseñar el firmware de ADC.
(2) Implementar el workaround documentado para la errata RP2350-E9 (ADC: evitar conversión
de canal flotante adyacente) desde el inicio del desarrollo.
(3) Suscribirse al foro oficial de Raspberry Pi para recibir notificaciones de nuevas erratas. &
C & Sem. 5 &
Código de ADC con workaround E9 implementado y comentado; lista de erratas revisada. \\[4pt]

R15 & Evitar / Mitigar &
(1) Ejecutar el DRC del fabricante (JLCPCB o PCBWay según la elección del equipo) sobre
el diseño KiCad antes de exportar Gerbers.
(2) Usar el plugin de validación de fabricabilidad de KiCad (Fabrication Toolkit).
(3) Enviar el pedido con opción de entrega express si el tiempo estándar supera 10 días hábiles.
(4) Tener identificado un segundo proveedor de respaldo con tiempo de entrega comparable. &
B & Sem. 6 &
DRC sin errores; pedido enviado antes del fin de sem. 6 con confirmación de plazo $\le 10$
días hábiles. \\[4pt]

\end{longtable}

---

## 6. Resumen ejecutivo

### 6.1 Cuadro de riesgos más críticos y estado de mitigación

\vspace{0.5em}

\begin{tabular}{>{\bfseries}p{0.7cm} p{4.0cm} p{3.5cm} p{4.2cm}}
\toprule
\textbf{ID} & \textbf{Descripción} & \textbf{Estado actual} & \textbf{Próxima acción} \\
\midrule
R01 & Decisiones HW abiertas (FET, driver, sensor, frecuencia) &
\cellcolor{red!30}Sin gestionar — todas abiertas &
Reunión de decisión técnica antes del fin de sem. 4. Responsable: B. \\[4pt]
R11 & Hito HIL sem. 16 en riesgo por cadena de dependencias &
\cellcolor{orange!30}Parcialmente mitigado — scaffolding SPI en marcha &
Alcanzar hito intermedio sem. 12 como indicador adelantado. \\[4pt]
R07 & Algoritmo MPPT no entra en presupuesto del MCU &
\cellcolor{yellow!20}Sin evidencia — no medido aún en target &
Medir huella del algoritmo base (P\&O en Rust) antes de sem. 10. \\[4pt]
R05 & Curva de aprendizaje Rust/RP2350 &
\cellcolor{yellow!20}Parcialmente resuelto — scaffolding funcional &
Completar integración ADC + PWM + SPI en binario único antes de sem. 7. \\
\bottomrule
\end{tabular}

\vspace{1em}

### 6.2 Conclusión del análisis

El proyecto `mpp-sdk` se encuentra al cierre de su Bloque 1 con avances concretos en los tres
streams: el scaffolding de SPI slave con PIO en Rust está en marcha, el abstract del paper ha sido
incorporado al repositorio, y la arquitectura del SDK Python está operativa con el algoritmo P\&O
como línea de base. Sin embargo, el análisis de riesgos revela que el momento actual es el más
sensible del cronograma completo: las próximas dos semanas concentran la mayor densidad de
decisiones irreversibles de todo el proyecto.

Los tres riesgos críticos (R01, R07 y R11) comparten una característica estructural: son riesgos
de cascada, donde la no-acción en la semana actual se amplifica en impacto a medida que avanza el
cronograma. R01 es el más urgente: no existe ninguna otra variable del proyecto que pueda
comprometer el Hito 1 (PCB a fabricación, semana 6) con tanta certeza como la demora en cerrar
las decisiones de componentes. La recomendación central de este análisis es que el equipo trate
el cierre de las decisiones de hardware como la tarea de mayor prioridad de la semana 4, por
encima de cualquier otro avance incremental en software o firmware. La reunión de decisión técnica
no es un evento organizativo menor: es la acción de mayor retorno sobre la inversión de tiempo
que el equipo puede tomar en este momento.

La adopción de Rust en el firmware, si bien no planeada, no constituye por sí misma un riesgo
crítico: el scaffolding existente es evidencia de que el equipo puede avanzar en este ecosistema.
El riesgo real (R07) es que la huella del algoritmo embebido no haya sido medida aún en el target,
y que esta medición solo pueda realizarse una vez que el hardware esté disponible (Bloque 3). La
acción de mitigación recomendada es construir un benchmark sintético en el RP2350 con el algoritmo
más complejo tan pronto como el hardware esté operativo, sin esperar a la integración completa del
lazo HIL.

Finalmente, el análisis confirma que el hito de la semana 16 (HIL extremo a extremo) es el evento
que define si el proyecto entrega una contribución experimental completa o una contribución de
simulación con arquitectura HIL validada parcialmente. La diferencia académica entre ambos
escenarios es significativa, y justifica que el equipo asigne el máximo de recursos disponibles a
eliminar o mitigar los riesgos de la cadena crítica en las semanas 5 y 6. El seguimiento del hito
intermedio de semana 12 es el mecanismo de alerta temprana que permitirá activar el plan de
contingencia con tiempo suficiente si la cadena presenta señales de atraso acumulado.
