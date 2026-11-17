# Hardware

KiCad source for the Proyecto 0.1V board, plus generated fabrication/export
artifacts. Source and generated files live side by side in this folder -
here's which is which.

## Source (edit these)

- `Proyecto0.1V.kicad_pro`, `Proyecto0.1V.kicad_pcb` - the KiCad project and
  PCB layout.
- `Proyecto0.1V.kicad_sch`, `Pico.kicad_sch`, `SepicConverter.kicad_sch`,
  `supplies.kicad_sch` - hierarchical schematic sheets.
- `untitled.kicad_sch` - despite the name, this **is** live source: the
  AnalogConverters sensing sheet. It's badly named, not stray - don't
  delete or rename it (renaming a sheet file requires a KiCad project-level
  edit for zero functional gain).
- `Custom_Library.pretty/` - custom footprint library used by the layout.

## Generated (regenerate, don't hand-edit)

- `Proyecto0.1V-schematic.pdf`, `Proyecto0.1V-pcb.pdf` - schematic/PCB PDF
  exports, generated with kicad-cli 10.0.1:

  ```sh
  kicad-cli sch export pdf Proyecto0.1V.kicad_sch \
      -o Proyecto0.1V-schematic.pdf
  kicad-cli pcb export pdf Proyecto0.1V.kicad_pcb \
      -o Proyecto0.1V-pcb.pdf \
      -l F.Cu,B.Cu,F.SilkS,B.SilkS,F.Fab,B.Fab,Edge.Cuts \
      --cl Edge.Cuts --mode-multipage --include-border-title
  ```

- `jlcpcb/gerber/`, `jlcpcb/production_files/` - JLCPCB fabrication outputs
  (Gerbers, drill files, BOM, CPL) generated from the KiCad project's own
  fabrication-output tooling.

Regenerate the PDFs and JLCPCB outputs after any schematic/layout change -
don't let them drift from the source files.

## Dimmer board

The 220 Vac halogen dimmer that lights the panels on the bench. It has its
own KiCad project in `dimmer/`. See `dimmer/README.md` for the board and the
mains safety warning.

### Dimmer source (edit these)

- `dimmer/esp32_dimmer.kicad_pro`, `.kicad_pcb`, `.kicad_sch`, `.kicad_dru` -
  project, layout, schematic and design rules.
- `dimmer/libraries/` - project-local symbols, footprints and 3D model.
- `dimmer/fp-lib-table`, `dimmer/sym-lib-table` - library tables. They point
  to `shared/` with `${KIPRJMOD}/../shared/...`, so keep that folder in place.
- `shared/` - ESP32-C3 SuperMini symbol, footprint and 3D model.
- `dimmer/docs/*.md` - design notes and calculations.

### Dimmer generated (regenerate, do not hand-edit)

- `dimmer/docs/schematic.pdf`, `dimmer/docs/BOM.csv`, `dimmer/docs/board-3d.png`
  - exports from the KiCad project. Regenerate after any change:

  ```sh
  kicad-cli sch export pdf dimmer/esp32_dimmer.kicad_sch \
      -o dimmer/docs/schematic.pdf
  ```

- `dimmer/docs/photo.jpg` - photo of the assembled board, metadata removed.
