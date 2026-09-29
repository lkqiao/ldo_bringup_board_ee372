# ldo_bringup_board_ee372

LDO bring up PCB for EE372.

- 20 µF / 390 mΩ RC dominant pole compensation at VOUT
- 0.1 µF cap at the NR pin for bandgap reference noise filtering
- Switch on the MD pin to toggle between high power and low power modes

## Project libraries

Both libraries are registered in the project-local `sym-lib-table` /
`fp-lib-table` under the nickname `ldo_bringup_board_ee372`, via
`${KIPRJMOD}`, so they resolve on any clone without per-machine setup.

| File | Contents |
|------|----------|
| `ldo_bringup_board_ee372.kicad_sym` | `LDO_DualMode_BGR_EE372` — 32-pin symbol + EP |
| `ldo_bringup_board_ee372.pretty/` | `QFN-32-1EP_7x7mm_P0.65mm_EP5.1x5.1mm_QuikPak` |

### Package

Quik-Pak **QP-QFN32-7MM-.65MM**, open-cavity QFN-32, rev A2. The numbers
come from the EE372B PCB Design Guidelines (Fall 2026, section 2), the
Quik-Pak mechanical drawing `QP-QFN7X7-32-650 PACKAGE.pdf` and the bonding
drawing `QP-QFN7X7-32-650 BONDING.dwg`.

| Parameter | Value | Source |
|---|---|---|
| Body | 7.000 x 7.000 mm, 0.800 tall | guidelines 2.1, package drawing |
| Leads | 32 (8/side), pitch 0.650 mm | guidelines 2.1, package drawing |
| Lead width x length | 0.300 x 0.380 mm | package drawing, bottom view |
| Lead-centre span per side | 4.550 mm | package drawing, bottom view |
| Exposed paddle (bottom) | 5.100 x 5.100 mm | package drawing, bottom view |
| Die attach surface (in the cavity) | 5.300 x 5.300 mm | bonding drawing note 3; not the land size |
| Pin-1 ID | 0.400 x 45 deg chamfer | package drawing, top view |

### Footprint

`QFN-32-1EP_7x7mm_P0.65mm_EP5.1x5.1mm_QuikPak`, checked against every
requirement in guidelines section 2.2.

| Pad size | Pitch | EP land | Courtyard |
|---|---|---|---|
| 0.30 x 0.85 mm | 0.65 mm | 5.10 x 5.10 mm | 8.26 x 8.26 mm |

- Lands extend 0.375 mm past the body edge and sit 0.475 mm from the EP land.
- 9 thermal vias, 0.3 mm drill, numbered 33 with the EP. They are tented on
  both sides because the EP has no full mask opening. Instead, 16 mask windows
  sit exactly over the 16 paste windows.
- EP paste is a 4x4 window pane at 52.5% coverage.
- Pin 1 is marked on silkscreen with a dot and a 0.4 mm chamfered corner.
- The 3D model is KiCad's stock `QFN-32-1EP_7x7mm_P0.65mm_EP5.46x5.46mm.step`,
  0.9 mm tall with a closed top. It is only for renders.

### Pinout

From the die pad map. Package pin 1 = the first pad down the **left** side,
i.e. the die orientation mark aligned to the package `PIN #1 ID`. Numbering
then runs CCW: left T→B (1-8), bottom L→R (9-16), right B→T (17-24),
top R→L (25-32). Pin 33 is the exposed pad.

| | | | |
|---|---|---|---|
| 1 VSS | 9 VDD | 17 VSS | 25 VDD |
| 2 VSS | 10 VSS | 18 VSS | 26 VDD |
| 3 VSS | 11 VSS | 19 VSS | 27 VDD |
| 4 VDD | 12 VSS | 20 VSS | 28 VSS |
| 5 IBIAS | 13 VSS | 21 VOUT | 29 MD |
| 6 VSS | 14 VSS | 22 VOUT | 30 NR |
| 7 VSS | 15 VSS | 23 VSS | 31 VSS |
| 8 VDD | 16 VDD | 24 VDD | 32 VDD |

Census: 18 × VSS, 9 × VDD, 2 × VOUT, 1 × MD, 1 × NR, 1 × IBIAS = 32.

### Known gaps, verify before fab

- **Pin names and the pin map are not verified against Cadence.** The names
  above come from the die floorplan figure. Guidelines 2.3 and 2.4 require the
  exact net names and pad types from the taped-out top-level cell, mapped
  through the fixed CEMiD bonding diagram.
- **The EP is tied to GND in the schematic.** Guidelines 2.2 says "The EP is
  its own net". Confirm with the course staff which reading they mean.
- **The symbol is laid out by package side.** Guidelines 2.3 asks for pins
  grouped by function (supplies top, grounds bottom, inputs left, outputs
  right).
