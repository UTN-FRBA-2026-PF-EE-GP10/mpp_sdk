import tkinter as tk
from tkinter import ttk

class SepicCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Diseño SEPIC - Ingreso de Datos")
        self.root.geometry("450x480")
        self.root.resizable(False, False)
        
        # Estilo visual limpio
        style = ttk.Style()
        style.theme_use('clam')
        
        # Diccionario para almacenar las variables de texto de entrada
        self.inputs = {
            "vin_min": tk.StringVar(value="5.0"),
            "vin_max": tk.StringVar(value="45.0"),
            "vout": tk.StringVar(value="20.0"),
            "iout": tk.StringVar(value="1.0"),
            "fsw": tk.StringVar(value="100.0"),      # En kHz
            "ripple_il": tk.StringVar(value="30.0"),  # En %
            "ripple_vc": tk.StringVar(value="5.0")    # En %
        }

        # Asignar el evento de actualización automática al tipear
        for var in self.inputs.values():
            var.trace_add("write", self.calcular_sepic)

        self.crear_interfaz()
        self.calcular_sepic()

    def crear_interfaz(self):
        # Contenedor de parámetros de entrada
        input_frame = ttk.LabelFrame(self.root, text=" Parámetros de Diseño (Ingreso Manual) ", padding=15)
        input_frame.pack(fill="x", padx=15, pady=10)

        # Helper para crear filas con cuadro de texto y su unidad de medida
        def crear_fila_entrada(label, var, sufijo, fila):
            ttk.Label(input_frame, text=label, font=("Helvetica", 10)).grid(row=fila, column=0, sticky="w", pady=5)
            entry = ttk.Entry(input_frame, textvariable=var, width=12, justify="right")
            entry.grid(row=fila, column=1, sticky="w", padx=10, pady=5)
            ttk.Label(input_frame, text=sufijo, font=("Helvetica", 10)).grid(row=fila, column=2, sticky="w", pady=5)

        # Generación de los campos de entrada
        crear_fila_entrada("Voltaje de Entrada Mínimo (Vin Mín):", self.inputs["vin_min"], "V", 0)
        crear_fila_entrada("Voltaje de Entrada Máximo (Vin Max):", self.inputs["vin_max"], "V", 1)
        crear_fila_entrada("Voltaje de Salida Deseado (Vout):", self.inputs["vout"], "V", 2)
        crear_fila_entrada("Corriente de Salida Máxima (Iout):", self.inputs["iout"], "A", 3)
        crear_fila_entrada("Frecuencia de Conmutación (fsw):", self.inputs["fsw"], "kHz", 4)
        crear_fila_entrada("Rizado de Corriente en Inductores (ΔIL):", self.inputs["ripple_il"], "%", 5)
        crear_fila_entrada("Rizado de Voltaje en C1 (ΔVc1):", self.inputs["ripple_vc"], "%", 6)

        input_frame.columnconfigure(1, weight=1)

        # Contenedor de resultados de salida
        output_frame = ttk.LabelFrame(self.root, text=" Componentes Calculados ", padding=15)
        output_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # Etiquetas para mostrar los resultados en tiempo real
        self.labels_res = {}
        variables_res = [
            ("Ciclo de Trabajo Máximo (Dmax):", "dmax"),
            ("Inductor de Entrada (L1):", "l1"),
            ("Inductor de Salida (L2):", "l2"),
            ("Capacitor de Acoplamiento (C1):", "c1"),
            ("Voltaje Mínimo en MOSFET / Diodo:", "v_semi")
        ]

        for idx, (texto, clave) in enumerate(variables_res):
            ttk.Label(output_frame, text=texto, font=("Helvetica", 10)).grid(row=idx, column=0, sticky="w", pady=4)
            self.labels_res[clave] = ttk.Label(output_frame, text="-", font=("Helvetica", 10, "bold"), foreground="#0066cc")
            self.labels_res[clave].grid(row=idx, column=1, sticky="e", padx=10)
            output_frame.columnconfigure(1, weight=1)

    def calcular_sepic(self, *args):
        try:
            # Intentar convertir los textos ingresados a números flotantes
            v_in_min = float(self.inputs["vin_min"].get())
            v_in_max = float(self.inputs["vin_max"].get())
            v_out = float(self.inputs["vout"].get())
            i_out = float(self.inputs["iout"].get())
            f_hz = float(self.inputs["fsw"].get()) * 1000  # Pasar kHz a Hz
            r_il = float(self.inputs["ripple_il"].get()) / 100.0
            r_vc = float(self.inputs["ripple_vc"].get()) / 100.0
            v_d = 0.5 # Caída fija del diodo

            # Validaciones básicas para evitar errores matemáticos al borrar/escribir
            if v_in_min <= 0 or v_out <= 0 or i_out <= 0 or f_hz <= 0 or r_il <= 0 or r_vc <= 0:
                return

            # 1. Ciclo de trabajo máximo
            d_max = (v_out + v_d) / (v_in_min + v_out + v_d)
            
            # 2. Corrientes promedio y rizados absolutos
            i_l1_avg = (i_out * d_max) / (1 - d_max)
            delta_il1 = i_l1_avg * r_il
            delta_il2 = i_out * r_il
            delta_vc1 = v_in_min * r_vc

            # 3. Cálculo de Componentes
            val_l1 = (v_in_min * d_max) / (delta_il1 * f_hz)
            val_l2 = (v_in_min * d_max) / (delta_il2 * f_hz)
            val_c1 = (i_out * d_max) / (delta_vc1 * f_hz)
            
            # 4. Tensión en semiconductores
            v_semis = max(v_in_min, v_in_max) + v_out

            # Actualizar textos en la interfaz convirtiendo a µH y µF
            self.labels_res["dmax"].config(text=f"{d_max * 100:.1f} %")
            self.labels_res["l1"].config(text=f"{val_l1 * 1e6:.2f} µH")
            self.labels_res["l2"].config(text=f"{val_l2 * 1e6:.2f} µH")
            self.labels_res["c1"].config(text=f"{val_c1 * 1e6:.2f} µF")
            self.labels_res["v_semi"].config(text=f"{v_semis:.1f} V")

        except ValueError:
            # Captura el error si el usuario está borrando el cuadro o ingresó una letra
            # Deja los resultados anteriores o vacíos hasta que se digite un número válido
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = SepicCalculatorApp(root)
    root.mainloop()
