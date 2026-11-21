"""Integrated LDO output noise, 9 kHz to 1 MHz, from the HP 8591E on J17 (x1000).

python3 scripts/spectrum_noise.py floor_1mA                 VIN off, saves floor_1mA.csv
python3 scripts/spectrum_noise.py hp_1mA --floor floor_1mA  VIN on, subtracts the floor
CSVs go in scripts/spectrum_noise_output/, and --floor looks there too.
"""
import argparse, csv, math, os, struct, sys, time
import pyvisa
import usb.core

RESOURCE = "USB0::1003::8293::HP8591E::0::INSTR"
RBW = 300.0
VBW = 300.0
SMOOTH = 31
REF_LEVEL_DBM = -30
ATTEN_DB = 10
R_IN = 50.0
SEGMENTS = [(9e3, 100e3)] + [(100e3 + k * 112.5e3, 100e3 + (k + 1) * 112.5e3) for k in range(8)]
POINTS = 401

# Args
ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("--floor", help="CSV from a VIN off run")
ap.add_argument("--gain", type=float, default=None,
                help="divide out the noise amp gain, 1000 on J17, 100 on J16. Off by default")
ap.add_argument("--sweeps", type=int, default=1, help="sweeps averaged per segment, about 33 s each")
args = ap.parse_args()
args.nogain = args.gain is None
if args.nogain:
    args.gain = 1.0
AVERAGES = args.sweeps
if AVERAGES < 1:
    sys.exit("--sweeps must be 1 or more")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spectrum_noise_output")
os.makedirs(OUT_DIR, exist_ok=True)


def in_out_dir(name):
    name = name if name.endswith(".csv") else name + ".csv"
    return name if os.path.dirname(name) else os.path.join(OUT_DIR, name)


out_path = in_out_dir(args.name)
if os.path.exists(out_path):
    sys.exit(f"{out_path} already exists, pick another name")

floor = None
if args.floor:
    floor_path = in_out_dir(args.floor)
    if not os.path.exists(floor_path):
        sys.exit(f"floor file {floor_path} not found")
    with open(floor_path) as fh:
        floor = [float(r["v2_hz_analyzer"]) for r in csv.DictReader(fh)]

# Connect
# A run that crashed mid-read leaves the adapter stuck, so reset it first.
adapter = usb.core.find(idVendor=0x03EB, idProduct=0x2065)
if adapter is None:
    sys.exit("GPIB adapter not found on USB")
adapter.reset()
time.sleep(3)
rm = pyvisa.ResourceManager("@py")
sa = rm.open_resource(RESOURCE)
sa.read_termination = "\n"
sa.write_termination = "\n"
sa.timeout = 60000
ident = sa.query("ID?").strip()
if ident != "HP8591E":
    sys.exit(f"unexpected ID reply {ident!r}")
print("connected to", ident)


def step(cmd):
    # The adapter refuses writes while the analyzer is busy, so every write ends in a query
    # and the next write only goes out after the reply.
    sa.query(cmd + "ID?")


def read_trace():
    sa.read_termination = None
    sa.write("MDS W;TDF B;TRA?")
    raw = sa.read_bytes(2 * POINTS)
    sa.read_termination = "\n"
    return [REF_LEVEL_DBM + (u - 8000) / 100 for u in struct.unpack(f">{POINTS}h", raw)]


# Setup
step("IP;SNGLS;")
step(f"AT {ATTEN_DB}DB;LG 10DB;RL {REF_LEVEL_DBM}DBM;DET SMP;")

freqs, readings = [], []
try:
    for n, (fa, fb) in enumerate(SEGMENTS):
        step(f"CF {(fa + fb) / 2:.0f}HZ;SP {fb - fa:.0f}HZ;RB {RBW:.0f}HZ;VB {VBW:.0f}HZ;")
        st = float(sa.query("ST?"))
        print(f"segment {n + 1}/{len(SEGMENTS)}  {fa / 1e3:.1f} to {fb / 1e3:.1f} kHz  "
              f"sweep {st:.2f} s x {AVERAGES}")
        step(f"VAVG {AVERAGES};CLRAVG;" if AVERAGES > 1 else "VAVG OFF;")
        # In single sweep, one TS keeps sweeping until all the averages are done.
        sa.timeout = int((AVERAGES * st * 1.5 + 30) * 1000)
        step("TS;")
        sa.timeout = 60000
        trace = read_trace()
        if max(trace) > REF_LEVEL_DBM - 2:
            print(f"  warning: trace reaches {max(trace):.1f} dBm, near the top of the screen")
        spacing = (fb - fa) / (POINTS - 1)
        last = POINTS if n == len(SEGMENTS) - 1 else POINTS - 1
        for i in range(last):
            freqs.append(fa + i * spacing)
            readings.append(trace[i])
finally:
    sa.read_termination = "\n"
    step("VAVG OFF;CONTS;")
    sa.close()

# Convert
# The +2.5 dB log detector correction holds for an average of dB values, so smooth in dB first.
half = SMOOTH // 2
smoothed = []
for i in range(len(readings)):
    win = readings[max(0, i - half):i + half + 1]
    smoothed.append(sum(win) / len(win))
corr = -10 * math.log10(1.12 * RBW) + 2.5
dbm_hz = [s + corr for s in smoothed]
v2_an = [10 ** ((d - 30) / 10) * R_IN for d in dbm_hz]

if floor is not None and len(floor) != len(v2_an):
    sys.exit(f"floor file has {len(floor)} points, this run has {len(v2_an)}")

v2_sub, flags = [], []
for i, v2 in enumerate(v2_an):
    if floor is None:
        v2_sub.append(v2)
        flags.append(0)
    else:
        flags.append(1 if v2 < floor[i] * 10 ** 0.1 else 0)
        v2_sub.append(max(v2 - floor[i], 0.0))

g2 = args.gain ** 2


def integrate(v2_list, lo, hi):
    total = 0.0
    for i in range(len(freqs) - 1):
        if freqs[i] >= lo and freqs[i + 1] <= hi:
            total += 0.5 * (v2_list[i] + v2_list[i + 1]) * (freqs[i + 1] - freqs[i])
    return math.sqrt(total / g2) * 1e6


# Save
with open(out_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "reading_dbm", "dbm_hz", "v2_hz_analyzer",
                "nv_rthz_out", "nv_rthz_out_floor_sub", "floor_within_1db"])
    for i in range(len(freqs)):
        w.writerow([f"{freqs[i]:.1f}", f"{readings[i]:.2f}", f"{dbm_hz[i]:.2f}", f"{v2_an[i]:.15e}",
                    f"{math.sqrt(v2_an[i] / g2) * 1e9:.3f}", f"{math.sqrt(v2_sub[i] / g2) * 1e9:.3f}",
                    flags[i]])

# Report
where = "at the analyzer input, no gain divided out" if args.nogain else f"at the LDO output, gain {args.gain:g} divided out"
print(f"saved {out_path}, {len(freqs)} points, sweeps {AVERAGES}")
print(f"values are {where}")
print(f"raw          9 kHz to 1 MHz  {integrate(v2_an, 9e3, 1e6):8.2f} uVrms")
if floor is not None:
    print(f"floor sub    9 kHz to 1 MHz  {integrate(v2_sub, 9e3, 1e6):8.2f} uVrms")
    print(f"floor sub    9 to 100 kHz    {integrate(v2_sub, 9e3, 100e3):8.2f} uVrms")
    print(f"floor sub    100 kHz to 1 MHz {integrate(v2_sub, 100e3, 1e6):7.2f} uVrms")
    print(f"points within 1 dB of the floor: {sum(flags)} of {len(flags)}")
