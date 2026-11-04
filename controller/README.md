# LDO bring-up controller

Teensy 4.1 firmware plus a localhost dashboard for the EE372B bring-up board.
The dashboard shows I_IN, I_OUT, V_IN, V_OUT, MD, and temperature live, and
drives the five load gates, MD, the load step, and the e-stop. Python scripts
can drive the same controls through `dashboard/ldo_client.py`, and the
dashboard follows whatever they change.

```
browser ──────────┐
ldo_client.py ────┼──HTTP──> dashboard/server.py ──USB serial──> Teensy (firmware/)
pyvisa scripts ───┘          owns the serial port
```

## Quickstart

1. Unplug anything on J8. Plug the Teensy into the laptop by USB.
2. In VS Code, open the folder `controller/firmware`.
3. Click the checkmark (Build), then the right arrow (Upload), both in the
   bottom bar. Wait for `[SUCCESS]`.
4. Open a terminal in `controller/dashboard` and run:
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only
   .venv/bin/python server.py
   ```
5. Open http://127.0.0.1:8372. The dot turns green when it's connected.
6. When you're done, press Ctrl+C in the terminal. Everything on the board
   turns off.

Steps 2 and 3 are only needed when the firmware changes. No board? Run
`.venv/bin/python server.py --sim` instead.

## Safety rules the firmware enforces

- Read pins (A1 to A6, A9) are inputs forever. A compile-time check fails the
  build if any of them is also an output. No pin can put 3.3 V on a chip pin.
- The load gates never sum to more than 20 mA (plan p4), using 18.7, 1.0, 15.0,
  10.0, and 5.0 mA for TG0 to TG4. During the MD square wave the limit is 10 mA
  (plan p23).
- Boot, e-stop, and the watchdog all turn every load off and set MD = 0
  (MD_SEL high, so Q6 holds MD at 0 V). The e-stop latches until Reset, and
  MD stays 0 after it.
- The watchdog trips if the server goes quiet for 2 s or the USB port closes.

## Board setup

- R51 fitted as **100 kΩ** (RC0603FR-07100KL), not 0 Ω, so the Teensy can read
  MD on A9. R46 and R47 (10k) give V_IN on A5 and V_OUT on A4.
- J9 and J11 fitted, J10 open, for Teensy control of MD.
- **Never plug anything into the J8 5V jack while USB is connected.** USB powers
  the Teensy and the 5V rail, and J8 would back-feed the laptop's USB port.

## Getting it running

You need VS Code with the PlatformIO IDE extension, Python 3, and a micro USB
cable that carries data (some charge-only cables don't).

### 1. One-time setup on a new laptop

In a terminal, from the board repo folder:

```bash
cd controller/dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

This makes a private Python environment in `dashboard/.venv` with pyserial in
it. Nothing is installed system-wide. Skip it if `.venv` already exists.

### 2. Flash the firmware onto the Teensy

1. In VS Code, File > Open Folder and pick `controller/firmware`. It has to be
   this folder, because PlatformIO only activates when `platformio.ini` is at
   the top. The first time, PlatformIO may spend a few minutes downloading the
   Teensy toolchain.
2. Click the checkmark in the bottom status bar (Build). The terminal should
   end with `[SUCCESS]`.
3. Make sure nothing is plugged into J8. Plug the Teensy into the laptop with
   the micro USB cable. It can be on the board or loose.
4. Click the right arrow in the bottom status bar (Upload). A small Teensy
   Loader window may pop up. The terminal should end with `[SUCCESS]`.
5. If it says it can't find the Teensy, press the white button on the Teensy
   once, then click Upload again.

You only reflash when the firmware code changes. The Teensy keeps it through
power cycles.

### 3. Start the dashboard

1. Stop anything else using the Teensy's port. That means closing the
   PlatformIO Serial Monitor and any other running copy of `server.py`. Only
   one program can open the port at a time.
2. In a terminal:
   ```bash
   cd controller/dashboard
   .venv/bin/python server.py
   ```
   It prints `Dashboard at http://127.0.0.1:8372 (real Teensy)`.
3. Open http://127.0.0.1:8372 in a browser. The dot at the top turns green and
   says connected, followed by the port (like `/dev/cu.usbmodem123`) and
   `ldo-ctrl 1.0`.
4. The Teensy starts with every load off and MD = 0. Readings update 20 times
   a second.

The server finds the Teensy by itself. If it shows offline:
- check the cable carries data (the Teensy shows up in VS Code's PlatformIO
  Devices list),
- check nothing else has the port open (step 1),
- or pass the port by hand, `.venv/bin/python server.py --port /dev/cu.usbmodemXXXX`.

If you unplug the Teensy, the dashboard shows offline and reconnects by
itself when you plug it back in.

### 4. First checks on the board (plan p5, section B)

- Row 3, with R21 lifted. Click each TG and check 3.3 V on J21 to J25 with the
  DMM, one at a time.
- Row 7. The I_IN and I_OUT tiles should match the DMM on TP28 and TP29 to 2%.
- Row 8. Board temp should read about 25 °C. Raw ADC at the bottom shows the
  ADT7310 word (0x0C80 at 25 °C).
- D5, with J9 and J11 fitted and J10 open. Clicking MD should move TP14 between
  3.3 V (MD = 0) and 0 V (MD = 1).
- Watchdog. Turn on a load, then press Ctrl+C on the server. The load should
  turn off at once, because closing the port trips the Teensy's watchdog.

### 5. Stopping

STOP on the page (or Esc) turns every load off and sets MD = 0. The button
then reads RESET. Click it to clear the latch. Outputs stay off until you
turn something back on.

Press Ctrl+C in the server's terminal to quit. The Teensy turns everything off
when the port closes.

### Without a board

```bash
.venv/bin/python server.py --sim
```

This runs a fake Teensy inside the server with made-up readings, for trying
the dashboard and scripts. It copies the firmware's rules, but it doesn't run
the firmware itself.

## Dashboard settings

- **Shunts.** Pick R4 = 10 Ω for IQ tests or 100 mΩ for load tests.
  I_IN = V_A2 / (500 R4).
- **3.3 V rail at TP27.** The ADC measures against the Teensy's 3.3 V rail.
  Measure TP27 with the DMM and enter it to fix the voltage scale (1% off is
  10 mV at 1 V).
- **Current offset.** With VIN and every load off, Zero current sense stores
  the INA190 output offsets and subtracts them from I_IN and I_OUT.
- **Record.** Writes every frame in volts, amps, and °C to `dashboard/logs/`.

## Load presets (plan p11, p13, p26)

| Preset | Gates |
|---|---|
| 1 mA | TG1 |
| 6 mA | TG1 + TG4 |
| 11 mA | TG1 + TG3 |
| 16 mA | TG1 + TG2 |
| 19.7 mA | TG1 + TG0 |
| 20 mA | TG2 + TG4 |

A step runs in the firmware. Step up turns every load off, holds 1 mA (TG1),
turns TG0 on for 19.7 mA, holds, then turns every load off. Step down does the
same from 19.7 mA to 1 mA. The change between the two holds is a single edge
on VG0 (plan p17). The hold is set on the dashboard, 1 s by default. The VG0
pulse repeats the same edge at a set rate so the scope triggers on every edge.

## Scripts

```python
import sys; sys.path.insert(0, "controller/dashboard")
from ldo_client import LDO, LDOError

ldo = LDO()
ldo.config(r4_ohm=0.1)
ldo.preset(1)
ldo.step_up(hold_s=1.0)      # off, 1 mA, 19.7 mA, off
ldo.wait_step_done()
print(ldo.readings())        # iin_a, iout_a, vin_v, vout_v, md_v, md_meas, temp_c, load_ma
try:
    ldo.set_loads(0b00101)   # TG0 + TG2, 33.7 mA
except LDOError as e:
    print(e)                 # loads sum to 33.7 mA, over the 20 mA limit
ldo.loads_off()
```

The server must be running. Every call shows up on the dashboard.

## Serial protocol

One command per line, `<id> <CMD> [args]`. The Teensy replies
`{"ack":<id>,"ok":true}` or `{"ack":<id>,"ok":false,"err":"..."}`.

| Command | Does |
|---|---|
| `LOAD <mask>` | set TG0 to TG4 at once, bit n = TGn |
| `TG <n> <0/1>` | one gate |
| `STEP UP <ms>` / `STEP DOWN <ms>` | timed step, each level held <ms> |
| `PULSE <hz> <duty>` / `PULSE OFF` | VG0 pulse from 1 mA |
| `MD <0/1>` | mode |
| `MDSQ <hz>` / `MDSQ OFF` | MD square wave |
| `ESTOP` / `RESET` | latch and clear |
| `HB` | heartbeat, the server sends it every 250 ms |
| `INFO` | firmware version and load table |

Telemetry is one JSON line every 50 ms with the mean ADC code per channel
(A1, A2, A3, A4, A5, A6, A9), the raw ADT7310 word, and the output state. The
server converts codes to units, so changing R4 never needs a reflash.
