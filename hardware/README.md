# Hardware

KiCad source for the Proyecto 0.1V board, plus generated fabrication/export
artifacts. Source and generated files live side by side in this folder -
here's which is which.

## Source (edit these)

- `Proyecto0.1V.kicad_pro`, `Proyecto0.1V.kicad_pcb` — the KiCad project and
  PCB layout.
- `Proyecto0.1V.kicad_sch`, `Pico.kicad_sch`, `SepicConverter.kicad_sch`,
  `supplies.kicad_sch` — hierarchical schematic sheets.
- `untitled.kicad_sch` — despite the name, this **is** live source: the
  AnalogConverters sensing sheet. It's badly named, not stray — don't
  delete or rename it (renaming a sheet file requires a KiCad project-level
  edit for zero functional gain).
- `Custom_Library.pretty/` — custom footprint library used by the layout.

## Generated (regenerate, don't hand-edit)

- `Proyecto0.1V-schematic.pdf`, `Proyecto0.1V-pcb.pdf` — schematic/PCB PDF
  exports, generated with kicad-cli 10.0.1:

  ```sh
  kicad-cli sch export pdf Proyecto0.1V.kicad_sch \
      -o Proyecto0.1V-schematic.pdf
  kicad-cli pcb export pdf Proyecto0.1V.kicad_pcb \
      -o Proyecto0.1V-pcb.pdf \
      -l F.Cu,B.Cu,F.SilkS,B.SilkS,F.Fab,B.Fab,Edge.Cuts \
      --cl Edge.Cuts --mode-multipage --include-border-title
  ```

- `jlcpcb/gerber/`, `jlcpcb/production_files/` — JLCPCB fabrication outputs
  (Gerbers, drill files, BOM, CPL) generated from the KiCad project's own
  fabrication-output tooling.

Regenerate the PDFs and JLCPCB outputs after any schematic/layout change -
don't let them drift from the source files.
