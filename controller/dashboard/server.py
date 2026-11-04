#!/usr/bin/env python3
"""LDO bring-up controller server.

Owns the Teensy's USB serial port, serves the dashboard at
http://127.0.0.1:8372, and exposes the same controls as an HTTP API for
Python scripts (see ldo_client.py). Run with --sim to test without a board.
"""

import argparse
import csv
import datetime as dt
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
LOGS = HERE / "logs"
CONFIG_PATH = HERE / "config.json"

PJRC_VID = 0x16C0
INA_GAIN = 500
ADC_FULL = 4096
MD_THRESHOLD_V = 0.9
LOADS_MA = [18.7, 1.0, 15.0, 10.0, 5.0]
ADC_KEYS = ["isense_out", "isense_in", "vout_b", "vout_ldo", "vdd_ldo", "vdd_a", "md"]

# Load presets from the bring-up plan, bit n = TGn.
PRESETS = {
    "0": 0b00000,
    "1": 0b00010,     # TG1
    "6": 0b10010,     # TG1 + TG4, load regulation p11
    "11": 0b01010,    # TG1 + TG3
    "16": 0b00110,    # TG1 + TG2
    "19.7": 0b00011,  # TG1 + TG0
    "20": 0b10100,    # TG2 + TG4, dropout and temperature
}

DEFAULT_CONFIG = {
    "r4_ohm": 0.1,
    "r3_ohm": 0.1,
    "v3v3": 3.3,
    "tare_in_v": 0.0,
    "tare_out_v": 0.0,
}


class CommandError(Exception):
    pass


def find_teensy():
    from serial.tools import list_ports

    for p in list_ports.comports():
        if p.vid == PJRC_VID:
            return p.device
    raise RuntimeError("no Teensy found on USB")


class Link:
    """The serial connection to the firmware, with reconnects and acks."""

    def __init__(self, port, sim, on_telemetry):
        self.port = port
        self.sim = sim
        self.on_telemetry = on_telemetry
        self.ser = None
        self.write_lock = threading.Lock()
        self.id_lock = threading.Lock()
        self.next_id = 1
        self.pending = {}
        self.connected = False
        self.port_name = None
        self.info = {}
        self.last_error = ""

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _open(self):
        if self.sim:
            from sim_teensy import SimTeensy

            self.port_name = "sim"
            return SimTeensy()
        import serial

        self.port_name = self.port or find_teensy()
        return serial.Serial(self.port_name, 115200, timeout=0.2)

    def _run(self):
        while True:
            try:
                self.ser = self._open()
                self.connected = True
                self.last_error = ""
                threading.Thread(target=self._fetch_info, daemon=True).start()
                while True:
                    raw = self.ser.readline()
                    if raw:
                        self._dispatch(raw)
            except Exception as exc:  # unplugged, not found, or permission denied
                self.connected = False
                self.last_error = str(exc)
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:
                    pass
                self.ser = None
                time.sleep(1.0)

    def _dispatch(self, raw):
        try:
            msg = json.loads(raw.decode(errors="replace"))
        except ValueError:
            return
        if "tel" in msg:
            self.on_telemetry(msg)
        elif "ack" in msg:
            slot = self.pending.get(msg["ack"])
            if slot:
                slot[1] = msg
                slot[0].set()

    def _fetch_info(self):
        try:
            self.info = self.send("INFO")
        except CommandError:
            pass

    def _heartbeat(self):
        while True:
            time.sleep(0.25)
            if self.connected:
                try:
                    self.send("HB", wait=False)
                except Exception:
                    pass

    def send(self, *parts, wait=True, timeout=1.0):
        if not self.connected or not self.ser:
            raise CommandError("Teensy not connected")
        with self.id_lock:
            rid = self.next_id
            self.next_id += 1
        slot = [threading.Event(), None]
        if wait:
            self.pending[rid] = slot
        line = " ".join([str(rid)] + [str(p) for p in parts]) + "\n"
        try:
            with self.write_lock:
                self.ser.write(line.encode())
            if not wait:
                return {"ok": True}
            if not slot[0].wait(timeout):
                raise CommandError(f"no reply from Teensy to {parts[0]}")
            reply = slot[1]
        finally:
            self.pending.pop(rid, None)
        if not reply.get("ok"):
            raise CommandError(reply.get("err", "command rejected"))
        return reply


class Controller:
    def __init__(self, port, sim):
        self.config = dict(DEFAULT_CONFIG)
        if CONFIG_PATH.exists():
            self.config.update(json.loads(CONFIG_PATH.read_text()))
        self.lock = threading.Lock()
        self.snapshot = {"connected": False}
        self.listeners = set()
        self.log_file = None
        self.log_writer = None
        self.log_path = None
        self.link = Link(port, sim, self._on_telemetry)
        self.link.start()

    # telemetry
    def _convert(self, tel):
        cfg = self.config
        volts = {k: c * cfg["v3v3"] / ADC_FULL for k, c in zip(ADC_KEYS, tel["adc"])}
        temp_word = tel["temp"]
        signed = temp_word - 0x10000 if temp_word & 0x8000 else temp_word
        mask = tel["vg"]
        load_ma = sum(LOADS_MA[i] for i in range(5) if mask >> i & 1)
        iin = (volts["isense_in"] - cfg["tare_in_v"]) / (INA_GAIN * cfg["r4_ohm"])
        iout = (volts["isense_out"] - cfg["tare_out_v"]) / (INA_GAIN * cfg["r3_ohm"])
        warnings = []
        if cfg["r4_ohm"] >= 1 and (mask or tel["pulse"]):
            warnings.append("R4 is set to 10 ohm with a load on. 20 mA would drop 0.2 V across it (plan p6).")
        if tel["estop"]:
            if tel["why"] == "e-stop":
                warnings.append("E-stop pressed. Reset to clear.")
            else:
                warnings.append(f"Stopped by the {tel['why'].replace('watchdog: ', 'watchdog, ')}. Reset to clear.")
        return {
            "connected": True,
            "port": self.link.port_name,
            "fw": self.link.info.get("fw", ""),
            "t_ms": tel["ms"],
            "raw": dict(zip(ADC_KEYS, tel["adc"]), temp=temp_word, samples=tel["n"]),
            "volts": volts,
            "iin_a": iin,
            "iout_a": iout,
            "vin_v": volts["vdd_ldo"],
            "vout_v": volts["vout_ldo"],
            "vdd_a_v": volts["vdd_a"],
            "vout_b_v": volts["vout_b"],
            "md_v": volts["md"],
            "md_meas": 1 if volts["md"] > MD_THRESHOLD_V else 0,
            "md_cmd": 0 if tel["msel"] else 1,
            "temp_c": (signed & ~0x7) / 128.0,
            "vg": mask,
            "load_ma": round(load_ma, 2),
            "loads_ma": LOADS_MA,
            "lim_ma": tel["lim"],
            "pulse": {"on": bool(tel["pulse"]), "hz": tel["phz"], "duty": tel["pduty"]},
            "mdsq": {"on": bool(tel["mdsq"]), "hz": tel["mhz"]},
            "step": {"phase": tel["step"], "dir": "up" if tel["sup"] else "down",
                     "hold_s": tel["shold"] / 1000},
            "estop": bool(tel["estop"]),
            "why": tel["why"],
            "config": dict(cfg),
            "warnings": warnings,
            "logging": str(self.log_path) if self.log_path else None,
        }

    def _on_telemetry(self, tel):
        snap = self._convert(tel)
        with self.lock:
            self.snapshot = snap
            listeners = list(self.listeners)
            if self.log_writer:
                self._log_row(snap)
        for q in listeners:
            try:
                q.put_nowait(snap)
            except queue.Full:
                pass

    def state(self):
        with self.lock:
            snap = dict(self.snapshot)
        if not self.link.connected:
            snap = {"connected": False, "error": self.link.last_error, "config": dict(self.config),
                    "logging": str(self.log_path) if self.log_path else None}
        return snap

    def subscribe(self):
        q = queue.Queue(maxsize=8)
        with self.lock:
            self.listeners.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.listeners.discard(q)

    # commands
    def load(self, mask):
        return self.link.send("LOAD", int(mask))

    def tg(self, n, on):
        return self.link.send("TG", int(n), 1 if on else 0)

    def preset(self, ma):
        key = ("%g" % float(ma))
        if key not in PRESETS:
            raise CommandError(f"no preset for {ma} mA, choose from {', '.join(PRESETS)}")
        return self.link.send("LOAD", PRESETS[key])

    def step(self, direction, hold_s=1.0):
        if direction not in ("up", "down"):
            raise CommandError("step direction must be up or down")
        return self.link.send("STEP", direction.upper(), int(round(float(hold_s) * 1000)))

    def pulse(self, hz, duty=50.0):
        return self.link.send("PULSE", float(hz), float(duty))

    def pulse_stop(self):
        return self.link.send("PULSE", "OFF")

    def md(self, value):
        return self.link.send("MD", int(value))

    def mdsq(self, hz):
        return self.link.send("MDSQ", float(hz))

    def mdsq_stop(self):
        return self.link.send("MDSQ", "OFF")

    def estop(self):
        return self.link.send("ESTOP")

    def reset(self):
        return self.link.send("RESET")

    def set_config(self, values):
        allowed = {"r4_ohm": (0.1, 10.0), "r3_ohm": (0.1,), "v3v3": None}
        for k, v in values.items():
            if k not in allowed:
                raise CommandError(f"unknown setting {k}")
            v = float(v)
            if allowed[k] and v not in allowed[k]:
                raise CommandError(f"{k} must be one of {allowed[k]}")
            if k == "v3v3" and not 3.0 <= v <= 3.6:
                raise CommandError("v3v3 must be 3.0 to 3.6 V")
            self.config[k] = v
        self._save_config()
        return {"ok": True, "config": dict(self.config)}

    def tare(self):
        snap = self.state()
        if not snap.get("connected"):
            raise CommandError("Teensy not connected")
        if snap["vg"] or snap["pulse"]["on"] or snap["step"]["phase"]:
            raise CommandError("turn every load off before zeroing")
        self.config["tare_in_v"] = snap["volts"]["isense_in"]
        self.config["tare_out_v"] = snap["volts"]["isense_out"]
        self._save_config()
        return {"ok": True, "config": dict(self.config)}

    def clear_tare(self):
        self.config["tare_in_v"] = 0.0
        self.config["tare_out_v"] = 0.0
        self._save_config()
        return {"ok": True, "config": dict(self.config)}

    def _save_config(self):
        CONFIG_PATH.write_text(json.dumps(self.config, indent=2) + "\n")

    # logging
    LOG_FIELDS = ["time", "t_ms", "iin_a", "iout_a", "vin_v", "vout_v", "vdd_a_v", "vout_b_v", "md_v",
                  "md_cmd", "temp_c", "vg", "load_ma", "pulse_hz", "mdsq_hz", "estop", "r4_ohm", "r3_ohm"]

    def log_start(self, name=""):
        with self.lock:
            if self.log_writer:
                raise CommandError(f"already recording to {self.log_path.name}")
            LOGS.mkdir(exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = "".join(c for c in name if c.isalnum() or c in "-_")
            self.log_path = LOGS / (f"{stamp}_{safe}.csv" if safe else f"{stamp}.csv")
            self.log_file = open(self.log_path, "w", newline="")
            self.log_writer = csv.writer(self.log_file)
            self.log_writer.writerow(self.LOG_FIELDS)
        return {"ok": True, "path": str(self.log_path)}

    def _log_row(self, s):
        self.log_writer.writerow([
            dt.datetime.now().isoformat(timespec="milliseconds"), s["t_ms"], s["iin_a"], s["iout_a"],
            s["vin_v"], s["vout_v"], s["vdd_a_v"], s["vout_b_v"], s["md_v"], s["md_cmd"], s["temp_c"],
            s["vg"], s["load_ma"], s["pulse"]["hz"] if s["pulse"]["on"] else 0,
            s["mdsq"]["hz"] if s["mdsq"]["on"] else 0, int(s["estop"]),
            s["config"]["r4_ohm"], s["config"]["r3_ohm"]])

    def log_stop(self):
        with self.lock:
            path = self.log_path
            if self.log_file:
                self.log_file.close()
            self.log_file = self.log_writer = self.log_path = None
        return {"ok": True, "path": str(path) if path else None}


def make_handler(ctl):
    routes = {
        "/api/load": lambda b: ctl.load(b["mask"]),
        "/api/tg": lambda b: ctl.tg(b["n"], b["on"]),
        "/api/preset": lambda b: ctl.preset(b["ma"]),
        "/api/step": lambda b: ctl.step(b["dir"], b.get("hold_s", 1.0)),
        "/api/pulse": lambda b: ctl.pulse(b["hz"], b.get("duty", 50.0)),
        "/api/pulse/stop": lambda b: ctl.pulse_stop(),
        "/api/md": lambda b: ctl.md(b["md"]),
        "/api/mdsq": lambda b: ctl.mdsq(b["hz"]),
        "/api/mdsq/stop": lambda b: ctl.mdsq_stop(),
        "/api/estop": lambda b: ctl.estop(),
        "/api/reset": lambda b: ctl.reset(),
        "/api/config": lambda b: ctl.set_config(b),
        "/api/tare": lambda b: ctl.tare(),
        "/api/tare/clear": lambda b: ctl.clear_tare(),
        "/api/log/start": lambda b: ctl.log_start(b.get("name", "")),
        "/api/log/stop": lambda b: ctl.log_stop(),
    }
    types = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/state":
                return self._json(200, ctl.state())
            if path == "/api/info":
                return self._json(200, {"presets": list(PRESETS), "loads_ma": LOADS_MA,
                                        "fw": ctl.link.info})
            if path == "/api/events":
                return self._events()
            name = "index.html" if path == "/" else path.removeprefix("/static/")
            file = (STATIC / name).resolve()
            if file.parent != STATIC or not file.is_file():
                return self._json(404, {"ok": False, "err": "not found"})
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", types.get(file.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in routes:
                return self._json(404, {"ok": False, "err": "unknown endpoint"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                result = routes[path](body)
                return self._json(200, result if isinstance(result, dict) else {"ok": True})
            except CommandError as exc:
                return self._json(409, {"ok": False, "err": str(exc)})
            except (KeyError, ValueError, TypeError) as exc:
                return self._json(400, {"ok": False, "err": f"bad request: {exc}"})

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = ctl.subscribe()
            try:
                self.wfile.write(f"data: {json.dumps(ctl.state())}\n\n".encode())
                while True:
                    try:
                        snap = q.get(timeout=1.0)
                    except queue.Empty:
                        snap = ctl.state()  # keeps the page updated while disconnected
                    self.wfile.write(f"data: {json.dumps(snap)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                ctl.unsubscribe(q)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="serial port, found automatically if omitted")
    ap.add_argument("--sim", action="store_true", help="use a simulated Teensy")
    ap.add_argument("--http-port", type=int, default=8372)
    args = ap.parse_args()
    ctl = Controller(args.port, args.sim)
    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(ctl))
    server.daemon_threads = True
    print(f"Dashboard at http://127.0.0.1:{args.http_port}  ({'simulated Teensy' if args.sim else 'real Teensy'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ctl.log_stop()


if __name__ == "__main__":
    main()
