"""Python access to the LDO controller, for test scripts.

Talks to server.py over HTTP, so the dashboard stays open and follows every
change a script makes. Standard library only.

    from ldo_client import LDO
    ldo = LDO()
    ldo.preset(1)                 # 1 mA, TG1 only
    ldo.step_up(hold_s=1.0)       # off, 1 mA, 19.7 mA, off
    print(ldo.readings()["vout_v"])
    ldo.estop()
"""

import json
import time
import urllib.error
import urllib.request


class LDOError(Exception):
    pass


class LDO:
    def __init__(self, url="http://127.0.0.1:8372", timeout=3.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _post(self, path, body=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("err", str(e))
            except ValueError:
                msg = str(e)
            raise LDOError(msg) from None

    def _get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=self.timeout) as r:
            return json.load(r)

    # readings
    def state(self):
        """Everything the dashboard shows, as one dict."""
        return self._get("/api/state")

    def readings(self):
        """Just the measured values, in volts, amps, and degrees C."""
        s = self.state()
        if not s.get("connected"):
            raise LDOError("Teensy not connected")
        keys = ["iin_a", "iout_a", "vin_v", "vout_v", "md_v", "md_meas", "temp_c", "load_ma"]
        return {k: s[k] for k in keys}

    def stream(self):
        """Yield every telemetry snapshot as it arrives (about 20 per second)."""
        with urllib.request.urlopen(self.url + "/api/events") as r:
            for line in r:
                if line.startswith(b"data: "):
                    yield json.loads(line[6:])

    def wait_for(self, condition, timeout=5.0):
        """Block until condition(state) is true, then return that state."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.state()
            if s.get("connected") and condition(s):
                return s
            time.sleep(0.05)
        raise LDOError("wait_for timed out")

    # loads
    def set_tg(self, n, on):
        return self._post("/api/tg", {"n": n, "on": bool(on)})

    def set_loads(self, mask):
        """Set all five load gates at once, bit n = TGn."""
        return self._post("/api/load", {"mask": mask})

    def preset(self, ma):
        """0, 1, 6, 11, 16, 19.7, or 20 mA, as the bring-up plan builds them."""
        return self._post("/api/preset", {"ma": ma})

    def loads_off(self):
        return self.set_loads(0)

    def step_up(self, hold_s=1.0):
        """Loads off, 1 mA for hold_s, 19.7 mA for hold_s, loads off. Returns at once."""
        return self._post("/api/step", {"dir": "up", "hold_s": hold_s})

    def step_down(self, hold_s=1.0):
        """Loads off, 19.7 mA for hold_s, 1 mA for hold_s, loads off. Returns at once."""
        return self._post("/api/step", {"dir": "down", "hold_s": hold_s})

    def wait_step_done(self, timeout=130.0):
        return self.wait_for(lambda s: s["step"]["phase"] == 0, timeout)

    def pulse_vg0(self, hz, duty=50.0):
        """Repeat the 1 to 19.7 mA step on VG0, starting from 1 mA."""
        return self._post("/api/pulse", {"hz": hz, "duty": duty})

    def stop_pulse(self):
        return self._post("/api/pulse/stop")

    # mode
    def set_md(self, md):
        """1 = high power, 0 = low power. Needs J9 and J11 fitted, J10 open."""
        return self._post("/api/md", {"md": md})

    def md_square(self, hz):
        """Square wave on MD at hz. The load must be 10 mA or less."""
        return self._post("/api/mdsq", {"hz": hz})

    def stop_md_square(self):
        return self._post("/api/mdsq/stop")

    # safety
    def estop(self):
        return self._post("/api/estop")

    def reset(self):
        """Clear a latched e-stop or watchdog trip. Outputs stay off."""
        return self._post("/api/reset")

    # settings and logging
    def config(self, **values):
        """Set r4_ohm (0.1 or 10), r3_ohm (0.1), or v3v3 (TP27 reading)."""
        return self._post("/api/config", values)

    def tare(self):
        return self._post("/api/tare")

    def start_log(self, name=""):
        return self._post("/api/log/start", {"name": name})

    def stop_log(self):
        return self._post("/api/log/stop")
