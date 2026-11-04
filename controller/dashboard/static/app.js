const LOADS = [18.7, 1.0, 15.0, 10.0, 5.0];
const PRESETS = [["0", 0b00000], ["1", 0b00010], ["6", 0b10010], ["11", 0b01010],
                 ["16", 0b00110], ["19.7", 0b00011], ["20", 0b10100]];
const HISTORY = 1200; // 60 s at 20 Hz
const $ = (id) => document.getElementById(id);

let state = { connected: false };
const history = { iin: [], iout: [], vin: [], vout: [], md: [], temp: [] };

async function post(path, body = {}) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok || j.ok === false) toast(j.err || `request failed (${r.status})`);
    return j;
  } catch (e) {
    toast("server not reachable");
  }
}

let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4000);
}

function current(a) {
  if (Math.abs(a) < 1e-3) return [(a * 1e6).toFixed(2), "µA"];
  return [(a * 1e3).toFixed(3), "mA"];
}

function push(key, v) {
  const h = history[key];
  h.push(v);
  if (h.length > HISTORY) h.shift();
}

function drawSpark(canvas, data) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (data.length < 2) return;
  let lo = Math.min(...data), hi = Math.max(...data);
  if (hi - lo < 1e-12) { hi += 1e-9; lo -= 1e-9; }
  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--trace");
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 1;
  ctx.beginPath();
  const x0 = w - (data.length / HISTORY) * w;
  data.forEach((v, i) => {
    const x = x0 + (i / HISTORY) * w;
    const y = h - 1 - ((v - lo) / (hi - lo)) * (h - 2);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

function build() {
  LOADS.forEach((ma, n) => {
    const b = document.createElement("button");
    b.className = "gate";
    b.id = `tg${n}`;
    b.innerHTML = `<div class="g">TG${n}</div><div class="m">${ma.toFixed(1)} mA</div>`;
    b.onclick = () => post("/api/tg", { n, on: !((state.vg >> n) & 1) });
    $("toggles").appendChild(b);
  });
  PRESETS.forEach(([p, mask]) => {
    const b = document.createElement("button");
    b.className = "btn";
    b.dataset.mask = mask;
    b.textContent = p === "0" ? "off" : p;
    b.onclick = () => post("/api/preset", { ma: p });
    $("presets").appendChild(b);
  });
}

function render(s) {
  state = s;
  $("conn").className = `status ${s.connected ? "on" : "off"}`;
  $("conn-text").textContent = s.connected ? "connected" : "offline";
  $("port").textContent = s.connected ? `${s.port}  ${s.fw || ""}` : (s.error || "");

  const banners = [...(s.warnings || [])];
  if (!s.connected) banners.unshift("Teensy not connected. Controls are disabled until it reconnects.");
  $("banners").innerHTML = banners.map((b) => `<div class="banner">${b}</div>`).join("");

  document.querySelectorAll("main button, main input, main select").forEach((el) => {
    if (!["log-name", "log-start", "log-stop", "v3v3", "v3v3-set", "r4", "r3", "tare-clear"].includes(el.id)) {
      el.disabled = !s.connected;
    }
  });
  if (s.config) {
    if (document.activeElement !== $("v3v3")) $("v3v3").value = s.config.v3v3.toFixed(3);
    $("r4").value = String(s.config.r4_ohm);
    const z = s.config.tare_in_v || s.config.tare_out_v;
    $("tare-state").textContent = z
      ? `−${(s.config.tare_in_v * 1e3).toFixed(1)} / −${(s.config.tare_out_v * 1e3).toFixed(1)} mV`
      : "";
  }
  $("log-state").textContent = s.logging ? s.logging.split("/").pop() : "off";
  const stop = $("estop");
  if (s.estop && !stop.classList.contains("latched")) {
    stop.classList.add("latched");
    stop.textContent = "RESET";
    stop.disabled = true;  // a double click on STOP must not reset straight away
    setTimeout(() => { stop.disabled = false; }, 1000);
  } else if (!s.estop && stop.classList.contains("latched")) {
    stop.classList.remove("latched");
    stop.textContent = "STOP";
    stop.disabled = false;
  }
  if (!s.connected) return;

  const [iin, uin] = current(s.iin_a);
  const [iout, uout] = current(s.iout_a);
  $("v-iin").textContent = iin; $("u-iin").textContent = uin;
  $("v-iout").textContent = iout; $("u-iout").textContent = uout;
  $("v-vin").textContent = s.vin_v.toFixed(4);
  $("v-vout").textContent = s.vout_v.toFixed(4);
  $("v-md").textContent = s.md_v.toFixed(3);
  $("v-mdlogic").textContent = s.md_meas ? "HIGH" : "LOW";
  $("v-temp").textContent = s.temp_c.toFixed(2);
  push("iin", s.iin_a); push("iout", s.iout_a); push("vin", s.vin_v);
  push("vout", s.vout_v); push("md", s.md_v); push("temp", s.temp_c);
  document.querySelectorAll(".cell").forEach((c) => drawSpark(c.querySelector("canvas"), history[c.dataset.key]));

  $("load-total").textContent = s.load_ma.toFixed(1);
  $("load-limit").textContent = s.lim_ma;
  $("load-bar").style.width = `${Math.min(100, (s.load_ma / 20) * 100)}%`;
  const stepping = s.step.phase !== 0;
  const locked = s.estop || s.pulse.on || stepping;
  LOADS.forEach((ma, n) => {
    const b = $(`tg${n}`);
    const on = ((s.vg >> n) & 1) === 1;
    b.classList.toggle("on", on);
    b.disabled = locked || (!on && s.load_ma + ma > s.lim_ma + 1e-6);
  });
  document.querySelectorAll("#presets .btn").forEach((b) => {
    b.classList.toggle("sel", Number(b.dataset.mask) === s.vg && !s.pulse.on);
    b.disabled = locked;
  });
  $("step-up").disabled = $("step-down").disabled = locked || s.mdsq.on;
  const levels = s.step.dir === "up" ? ["1 mA", "19.7 mA"] : ["19.7 mA", "1 mA"];
  $("step-state").textContent = stepping ? `● ${levels[s.step.phase - 1]}` : "";
  $("pulse-start").disabled = locked || s.mdsq.on || s.vg !== 0b00010;
  $("pulse-stop").disabled = !s.pulse.on;
  $("pulse-state").textContent = s.pulse.on ? `● ${s.pulse.hz} Hz` : "";

  $("md-cmd").textContent = s.mdsq.on ? `square ${s.mdsq.hz} Hz` : `MD = ${s.md_cmd}`;
  $("md1").classList.toggle("sel", s.md_cmd === 1 && !s.mdsq.on);
  $("md0").classList.toggle("sel", s.md_cmd === 0 && !s.mdsq.on);
  $("md1").disabled = $("md0").disabled = s.mdsq.on;
  $("mdsq-start").disabled = s.estop || s.mdsq.on || s.pulse.on || stepping;
  $("mdsq-stop").disabled = !s.mdsq.on;
  $("mdsq-state").textContent = s.mdsq.on ? `● ${s.mdsq.hz} Hz` : "";

  const r = s.raw;
  const f = (x) => x.toFixed(1).padStart(7);
  $("debug").textContent =
    `A1 isense_out ${f(r.isense_out)}   A2 isense_in ${f(r.isense_in)}   A9 md   ${f(r.md)}\n` +
    `A4 vout_ldo   ${f(r.vout_ldo)}   A5 vdd_ldo   ${f(r.vdd_ldo)}   ADT7310 0x${r.temp.toString(16).toUpperCase().padStart(4, "0")}\n` +
    `A3 vout (R48) ${f(r.vout_b)}   A6 vdd (R45) ${f(r.vdd_a)}   ${r.samples} samples / 50 ms`;
}

function applyTheme(t) {
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = t || (dark ? "dark" : "light");
}

function wire() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) {}
  applyTheme(saved);
  $("theme").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", next); } catch (e) {}
    applyTheme(next);
  };
  $("estop").onclick = () => post($("estop").classList.contains("latched") ? "/api/reset" : "/api/estop");
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") post("/api/estop"); });
  const hold = () => parseFloat($("step-hold").value);
  $("step-up").onclick = () => post("/api/step", { dir: "up", hold_s: hold() });
  $("step-down").onclick = () => post("/api/step", { dir: "down", hold_s: hold() });
  $("pulse-start").onclick = () =>
    post("/api/pulse", { hz: parseFloat($("pulse-hz").value), duty: parseFloat($("pulse-duty").value) });
  $("pulse-stop").onclick = () => post("/api/pulse/stop");
  $("md1").onclick = () => post("/api/md", { md: 1 });
  $("md0").onclick = () => post("/api/md", { md: 0 });
  $("mdsq-start").onclick = () => post("/api/mdsq", { hz: parseFloat($("mdsq-hz").value) });
  $("mdsq-stop").onclick = () => post("/api/mdsq/stop");
  $("r4").onchange = () => post("/api/config", { r4_ohm: parseFloat($("r4").value) });
  $("v3v3-set").onclick = () => post("/api/config", { v3v3: parseFloat($("v3v3").value) });
  $("tare").onclick = () => post("/api/tare");
  $("tare-clear").onclick = () => post("/api/tare/clear");
  $("log-start").onclick = () => post("/api/log/start", { name: $("log-name").value });
  $("log-stop").onclick = () => post("/api/log/stop");
}

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => render(JSON.parse(e.data));
  es.onerror = () => {
    render({ connected: false, error: "dashboard server not running" });
    es.close();
    setTimeout(connect, 1000);
  };
}

build();
wire();
connect();
