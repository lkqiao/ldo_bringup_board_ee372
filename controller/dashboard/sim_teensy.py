"""A fake Teensy that speaks the same serial protocol as the firmware.

Used by `server.py --sim` to test the dashboard and scripts with no board.
The interlocks mirror firmware/src/loads.cpp. The readings are made up:
VIN 1.8 V, VOUT 1.0 V, I_Q 47 uA (MD = 1) or 25 uA (MD = 0), R3 = R4 = 100 mohm.
"""

import queue
import random
import threading
import time

LOAD_TENTHS = [187, 10, 150, 100, 50]
LIMIT, LIMIT_MDSQ = 200, 100
TG0, TG1 = 1, 2


def tenths(mask):
    return sum(t for i, t in enumerate(LOAD_TENTHS) if mask >> i & 1)


class SimTeensy:
    def __init__(self):
        self.out = queue.Queue()
        self.mask = 0
        self.msel = 1  # MD = 0 by default
        self.pulse = None  # (hz, duty)
        self.mdsq = None  # hz
        self.estop = False
        self.why = ""
        self.step = 0  # 0 idle, 1 first hold, 2 second hold
        self.step_up = True
        self.step_hold = 1.0
        self.step_t0 = 0.0
        self.last_rx = time.monotonic()
        self.dtr = True
        self.alive = True
        self.t0 = time.monotonic()
        threading.Thread(target=self._loop, daemon=True).start()

    # pyserial-like interface
    def write(self, data):
        for line in data.decode().splitlines():
            if line.strip():
                self._handle(line.strip())
        return len(data)

    def readline(self):
        try:
            return self.out.get(timeout=0.2)
        except queue.Empty:
            return b""

    def close(self):
        self.dtr = False
        time.sleep(0.06)
        self.alive = False

    @property
    def is_open(self):
        return self.alive

    # firmware behaviour
    def _emit(self, s):
        self.out.put((s + "\n").encode())

    def _limit(self):
        return LIMIT_MDSQ if self.mdsq else LIMIT

    def _check(self, m):
        if m > 31:
            return "mask must be 0 to 31"
        s, lim = tenths(m), self._limit()
        if s > lim:
            extra = " during the MD square wave" if self.mdsq else ""
            return f"loads sum to {s // 10}.{s % 10} mA, over the {lim // 10} mA limit{extra}"
        return None

    def _set_mask(self, m):
        if self.estop:
            return "e-stop latched, send RESET first"
        if self.step:
            return "wait for the step sequence to finish"
        if self.pulse:
            return "stop the VG0 pulse first"
        err = self._check(m)
        if not err:
            self.mask = m
        return err

    def _safe(self, why):
        self.step = 0
        self.pulse = None
        self.mdsq = None
        self.mask = 0
        self.msel = 1
        if not self.estop:
            self.why = why
        self.estop = True

    def _handle(self, line):
        parts = line.split()
        if len(parts) < 2:
            return
        rid, cmd, args = parts[0], parts[1], parts[2:]
        self.last_rx = time.monotonic()
        err = None
        if cmd == "HB":
            pass
        elif cmd == "INFO":
            self._emit(f'{{"ack":{rid},"ok":true,"fw":"ldo-ctrl 1.0 (sim)","loads":[18.7,1.0,15.0,10.0,5.0],'
                       f'"lim":20,"lim_mdsq":10,"adt_id":195}}')
            return
        elif cmd == "ESTOP":
            self._safe("e-stop")
        elif cmd == "RESET":
            self.estop, self.why = False, ""
        elif cmd == "LOAD" and args:
            err = self._set_mask(int(args[0]))
        elif cmd == "TG" and len(args) == 2:
            n, on = int(args[0]), int(args[1])
            if not 0 <= n <= 4:
                err = "TG must be 0 to 4"
            else:
                m = self.mask | (1 << n) if on else self.mask & ~(1 << n)
                err = self._set_mask(m)
        elif cmd == "STEP" and args and args[0] in ("UP", "DOWN"):
            hold = int(args[1]) if len(args) > 1 else 1000
            if self.estop:
                err = "e-stop latched, send RESET first"
            elif self.step:
                err = "step sequence already running"
            elif self.pulse:
                err = "stop the VG0 pulse first"
            elif not 50 <= hold <= 60000:
                err = "hold must be 0.05 to 60 s"
            else:
                err = self._check(TG1 | TG0)
            if not err:
                self.step_up = args[0] == "UP"
                self.step_hold = hold / 1000
                self.mask = TG1 if self.step_up else TG1 | TG0
                self.step = 1
                self.step_t0 = time.monotonic()
        elif cmd == "PULSE" and args:
            if args[0] == "OFF":
                self.pulse = None
            else:
                hz = float(args[0])
                duty = float(args[1]) if len(args) > 1 else 50.0
                if self.estop:
                    err = "e-stop latched, send RESET first"
                elif self.pulse:
                    err = "VG0 pulse already running"
                elif self.step:
                    err = "wait for the step sequence to finish"
                elif self.mdsq:
                    err = "stop the MD square wave first"
                elif self.mask != TG1:
                    err = "the VG0 pulse starts from 1 mA (TG1 only)"
                elif not 0.1 <= hz <= 1000:
                    err = "pulse frequency must be 0.1 to 1000 Hz"
                elif not 5 <= duty <= 95:
                    err = "pulse duty must be 5 to 95 %"
                else:
                    self.pulse = (hz, duty)
        elif cmd == "MD" and args:
            md = int(args[0])
            if md not in (0, 1):
                err = "MD must be 0 or 1"
            elif self.mdsq:
                err = "stop the MD square wave first"
            else:
                self.msel = 1 if md == 0 else 0
        elif cmd == "MDSQ" and args:
            if args[0] == "OFF":
                if self.mdsq:
                    self.mdsq = None
                    self.msel = 1
            else:
                hz = float(args[0])
                s = tenths(self.mask)
                if self.estop:
                    err = "e-stop latched, send RESET first"
                elif self.mdsq:
                    err = "MD square wave already running"
                elif self.pulse:
                    err = "stop the VG0 pulse first"
                elif self.step:
                    err = "wait for the step sequence to finish"
                elif not 0.1 <= hz <= 1000:
                    err = "MD square wave must be 0.1 to 1000 Hz"
                elif s > LIMIT_MDSQ:
                    err = f"loads sum to {s // 10}.{s % 10} mA, the MD square wave needs 10 mA or less"
                else:
                    self.mdsq = hz
        else:
            err = "unknown command"
        if err:
            self._emit(f'{{"ack":{rid},"ok":false,"err":"{err}"}}')
        else:
            self._emit(f'{{"ack":{rid},"ok":true}}')

    def _active(self):
        return bool(self.mask or self.pulse or self.mdsq or self.msel != 1 or self.step)

    def _loop(self):
        vref = 3.3
        while self.alive:
            time.sleep(0.05)
            now = time.monotonic()
            if self._active():
                if not self.dtr:
                    self._safe("watchdog: USB port closed")
                elif now - self.last_rx > 2.0:
                    self._safe("watchdog: no heartbeat for 2 s")
            if self.step and now - self.step_t0 >= self.step_hold:
                if self.step == 1:
                    self.mask = TG1 | TG0 if self.step_up else TG1
                    self.step, self.step_t0 = 2, now
                else:
                    self.mask, self.step = 0, 0
            if self.mdsq:
                self.msel = int((now - self.t0) * self.mdsq * 2) % 2
            mask = self.mask
            if self.pulse:
                hz, duty = self.pulse
                phase = ((now - self.t0) * hz) % 1.0
                mask = mask | TG0 if phase < duty / 100 else mask & ~TG0
            md = 0 if self.msel else 1
            iout = tenths(mask) / 10 * 1e-3 * (1 - 0.0012)
            iq = 47.12e-6 if md else 25.41e-6
            vout = 1.0057 - 1.15e-3 * iout / 0.0197
            v = {
                "iout": 500 * 0.1 * iout + random.gauss(0, 0.4e-3),
                "iin": 500 * 0.1 * (iout + iq) + random.gauss(0, 0.4e-3),
                "vout_b": vout - 0.1 * iout,
                "vout": vout,
                "vin": 1.8 - 0.1 * (iout + iq),
                "vdd": 1.8,
                "md": 1.8 if md else 0.0,
            }
            codes = [max(0.0, x / vref * 4096 + random.gauss(0, 0.6)) for x in
                     (v["iout"], v["iin"], v["vout_b"], v["vout"], v["vin"], v["vdd"], v["md"])]
            temp = int((25.0 + random.gauss(0, 0.05)) * 128) & 0xFFF8  # 25 C reads 0x0C80
            p = self.pulse or (0.0, 0.0)
            self._emit(
                '{"tel":1,"ms":%d,"adc":[%s],"n":500,"temp":%d,"vg":%d,"msel":%d,"pulse":%d,'
                '"phz":%.3f,"pduty":%.1f,"mdsq":%d,"mhz":%.3f,"step":%d,"sup":%d,"shold":%d,"lim":%d,'
                '"estop":%d,"why":"%s"}'
                % (int((now - self.t0) * 1000), ",".join("%.2f" % c for c in codes), temp, self.mask,
                   self.msel, 1 if self.pulse else 0, p[0], p[1], 1 if self.mdsq else 0,
                   self.mdsq or 0.0, self.step, 1 if self.step_up else 0,
                   int(self.step_hold * 1000), self._limit() // 10, 1 if self.estop else 0, self.why))
