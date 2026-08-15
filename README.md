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
| `ldo_bringup_board_ee372.pretty/` | `QFN-32-1EP_7x7mm_P0.65mm_EP5.3x5.3mm_QuikPak` |

### Package

Quik-Pak **QP-QFN32-7MM-.65MM**, open-cavity QFN-32. Dimensions were
extracted from the vendor bonding drawing
`QP-QFN7X7-32-650 BONDING.dwg` (rev A2, 4/5/10) by decoding the DWG
directly, not read off a datasheet:

| Parameter | Value | Source |
|---|---|---|
| Body | 7.00 × 7.00 mm | drawing note 1 + geometry (14.000 u @ 2× scale) |
| Lead count | 32 (8/side) | drawing note 2 |
| Pitch | 0.650 mm | measured, lead-edge ticks |
| Lead width | 0.300 mm | measured, lead-edge ticks |
| Die attach pad | 5.300 × 5.300 mm | drawing note 3 + geometry |

Land pattern is KiCad's IPC-derived `QFN-32-1EP_7x7mm_P0.65mm`
(pads 0.85 × 0.25 mm at 3.45 mm radius) with the exposed pad resized
5.4 → **5.30 mm** to match the drawing. Pad centres were verified against
the DWG lead positions to **0.000 µm**.

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

### Known gaps — verify before fab

- **Die rotation is a decision, not a measurement.** The die and the cavity
  are both square and the pad ring is symmetric, so the die can be bonded in
  four orientations. The table above assumes the conventional one. The
  footprint and the board layout are unaffected by this choice; only which
  side each signal exits changes. Fix it in the bonding diagram submitted to
  the assembler, and regenerate the symbol if it differs.
- The bonding drawing is a **top/cavity view only**. It contains no bottom
  view, no side view and no DIMENSION entities, so the **solder-side lead
  length** is not specified by it. The land pattern's 0.85 mm pad length is
  IPC-derived, not vendor-confirmed.
- The **EP land is set from the 5.30 mm die attach pad**, which is the
  cavity-side paddle. Confirm the bottom-side exposed metal against the
  Quik-Pak mechanical drawing before release. Note the die substrate sits on
  this paddle, so it is almost certainly at VSS — confirm before tying it.

