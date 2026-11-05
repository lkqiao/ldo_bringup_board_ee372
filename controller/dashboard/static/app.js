const LOADS = [18.7, 1.0, 15.0, 10.0, 5.0];
const PRESETS = [["0", 0b00000], ["1", 0b00010], ["6", 0b10010], ["11", 0b01010],
                 ["16", 0b00110], ["19.7", 0b00011], ["20", 0b10100]];
const SPARK = 1200;     // sparkline shows the last 60 s at 20 Hz
const HISTORY = 6000;  // keep 5 min for the expanded graph
const $ = (id) => document.getElementById(id);

let state = { connected: false };
const history = {};
const SERIES = {
  iin: { name: "I<sub>IN</sub>", axis: "I_IN", current: true },
  iout: { name: "I<sub>OUT</sub>", axis: "I_OUT", current: true },
  vin: { name: "V<sub>IN</sub>", axis: "V_IN", unit: "V", digits: 4 },
  vout: { name: "V<sub>OUT</sub>", axis: "V_OUT", unit: "V", digits: 4 },
  md: { name: "MD", axis: "MD", unit: "V", digits: 3 },
  temp: { name: "Board temp", axis: "Temperature", unit: "°C", digits: 2 },
};
Object.keys(SERIES).forEach((k) => { history[k] = { t: [], v: [] }; });

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

let v3v3Dirty = false;
let v3v3Sent = null;
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

function push(key, t, v) {
  const h = history[key];
  if (h.t.length && t < h.t[h.t.length - 1]) { h.t.length = 0; h.v.length = 0; }  // Teensy rebooted
  h.t.push(t);
  h.v.push(v);
  if (h.t.length > HISTORY) { h.t.shift(); h.v.shift(); }
}

function drawSpark(canvas, series) {
  const data = series.v.slice(-SPARK);
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
  const x0 = w - (data.length / SPARK) * w;
  data.forEach((v, i) => {
    const x = x0 + (i / SPARK) * w;
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
    if (v3v3Sent !== null && Math.abs(s.config.v3v3 - v3v3Sent) < 1e-9) v3v3Sent = null;
    if (!v3v3Dirty && v3v3Sent === null) $("v3v3").value = s.config.v3v3.toFixed(3);
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
  const t = s.t_ms / 1000;
  push("iin", t, s.iin_a); push("iout", t, s.iout_a); push("vin", t, s.vin_v);
  push("vout", t, s.vout_v); push("md", t, s.md_v); push("temp", t, s.temp_c);
  document.querySelectorAll(".cell").forEach((c) => drawSpark(c.querySelector("canvas"), history[c.dataset.key]));
  if (zoom.key) drawZoom();

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

// expanded graph
const zoom = { key: null, cell: null, range: 60, hoverX: null };

function niceStep(span, n) {
  const raw = span / n;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p;
}

function zoomScale(meta, vals) {
  if (!meta.current) return { k: 1, unit: meta.unit };
  const m = Math.max(...vals.map(Math.abs));
  return m < 1e-3 ? { k: 1e6, unit: "µA" } : { k: 1e3, unit: "mA" };
}

function drawZoom() {
  const meta = SERIES[zoom.key];
  const h = history[zoom.key];
  const canvas = $("zoom-canvas");
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue("--ink"), dim = css.getPropertyValue("--dim");
  const rule = css.getPropertyValue("--rule"), on = css.getPropertyValue("--on");
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.font = `11px ${css.getPropertyValue("--mono")}`;

  const tEnd = h.t.length ? h.t[h.t.length - 1] : 0;
  let i0 = h.t.findIndex((t) => t >= tEnd - zoom.range);
  if (i0 < 0) i0 = h.t.length;
  const ts = h.t.slice(i0), raw = h.v.slice(i0);
  if (ts.length < 2) {
    ctx.fillStyle = dim; ctx.fillText("waiting for data", 20, 24);
    $("zoom-stats").textContent = "";
    return;
  }
  const sc = zoomScale(meta, raw);
  const vs = raw.map((v) => v * sc.k);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  const mean = vs.reduce((a, b) => a + b, 0) / vs.length;
  const minLo = lo, maxHi = hi;
  const span0 = hi - lo || Math.max(Math.abs(hi) * 1e-3, 1e-6);
  lo -= span0 * 0.12; hi += span0 * 0.12;

  const L = 78, R = 18, T = 12, B = 42;
  const pw = W - L - R, ph = H - T - B;
  const X = (t) => L + ((t - (tEnd - zoom.range)) / zoom.range) * pw;
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * ph;

  // grid and value axis
  const ys = niceStep(hi - lo, 6);
  const dec = Math.max(0, -Math.floor(Math.log10(ys)));
  ctx.strokeStyle = rule; ctx.fillStyle = dim; ctx.lineWidth = 1;
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let v = Math.ceil(lo / ys) * ys; v <= hi + ys * 1e-6; v += ys) {
    const y = Math.round(Y(v)) + 0.5;
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + pw, y); ctx.stroke();
    ctx.fillText(v.toFixed(dec), L - 8, y);
  }
  // time axis
  const xs = niceStep(zoom.range, 6);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let s = 0; s <= zoom.range + 1e-9; s += xs) {
    const x = Math.round(X(tEnd - s)) + 0.5;
    ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, T + ph); ctx.stroke();
    ctx.fillText(s === 0 ? "now" : `−${+s.toFixed(3)}`, x, T + ph + 6);
  }
  ctx.strokeStyle = dim;
  ctx.strokeRect(L + 0.5, T + 0.5, pw, ph);
  ctx.fillText("time (s)", L + pw / 2, T + ph + 24);
  ctx.save();
  ctx.translate(16, T + ph / 2); ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = "middle";
  ctx.fillText(`${meta.axis} (${sc.unit})`, 0, 0);
  ctx.restore();

  // trace
  ctx.save();
  ctx.beginPath(); ctx.rect(L, T, pw, ph); ctx.clip();
  ctx.strokeStyle = ink; ctx.lineWidth = 1.4; ctx.lineJoin = "round";
  ctx.beginPath();
  ts.forEach((t, i) => (i ? ctx.lineTo(X(t), Y(vs[i])) : ctx.moveTo(X(t), Y(vs[i]))));
  ctx.stroke();
  ctx.fillStyle = on;
  ctx.beginPath(); ctx.arc(X(tEnd), Y(vs[vs.length - 1]), 3.5, 0, 2 * Math.PI); ctx.fill();
  ctx.restore();

  const vd = meta.current ? 3 : meta.digits;
  const fmt = (v) => `${v.toFixed(vd)} ${sc.unit}`;

  // cursor readout
  if (zoom.hoverX !== null && zoom.hoverX >= L && zoom.hoverX <= L + pw) {
    const tq = tEnd - zoom.range + ((zoom.hoverX - L) / pw) * zoom.range;
    let best = 0;
    ts.forEach((t, i) => { if (Math.abs(t - tq) < Math.abs(ts[best] - tq)) best = i; });
    const x = X(ts[best]), y = Y(vs[best]);
    ctx.strokeStyle = dim; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, T + ph); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = ink;
    ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 2 * Math.PI); ctx.fill();
    const label = `${(ts[best] - tEnd).toFixed(2)} s   ${fmt(vs[best])}`;
    const tw = ctx.measureText(label).width + 14;
    const bx = Math.min(x + 10, L + pw - tw), by = Math.max(T + 4, Math.min(y - 26, T + ph - 24));
    ctx.fillStyle = css.getPropertyValue("--panel"); ctx.strokeStyle = rule;
    ctx.fillRect(bx, by, tw, 20); ctx.strokeRect(bx + 0.5, by + 0.5, tw, 20);
    ctx.fillStyle = ink; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillText(label, bx + 7, by + 10);
  }

  $("zoom-value").textContent = fmt(vs[vs.length - 1]);
  $("zoom-stats").innerHTML =
    `<span>min <b>${fmt(minLo)}</b></span><span>max <b>${fmt(maxHi)}</b></span>` +
    `<span>mean <b>${fmt(mean)}</b></span><span>p-p <b>${fmt(maxHi - minLo)}</b></span>` +
    `<span>${vs.length} points over ${(ts[ts.length - 1] - ts[0]).toFixed(1)} s</span>`;
}

function flipTransform(from, to) {
  return `translate(${from.left - to.left}px, ${from.top - to.top}px) ` +
         `scale(${from.width / to.width}, ${from.height / to.height})`;
}

function openZoom(cell) {
  zoom.key = cell.dataset.key;
  zoom.cell = cell;
  zoom.hoverX = null;
  const z = $("zoom"), panel = $("zoom-panel");
  z.style.top = `${document.querySelector("header").offsetHeight}px`;
  $("zoom-name").innerHTML = SERIES[zoom.key].name;
  document.querySelectorAll("#zoom-range .btn").forEach((b) => b.classList.toggle("sel", +b.dataset.s === zoom.range));
  z.classList.remove("hidden");
  z.classList.add("fade0");
  const to = panel.getBoundingClientRect();
  panel.style.transition = "none";
  panel.style.transform = flipTransform(cell.getBoundingClientRect(), to);
  drawZoom();
  requestAnimationFrame(() => requestAnimationFrame(() => {
    panel.style.transition = "transform 0.26s cubic-bezier(0.2, 0.8, 0.2, 1)";
    panel.style.transform = "none";
    z.classList.remove("fade0");
  }));
}

function closeZoom() {
  if (!zoom.key) return;
  const z = $("zoom"), panel = $("zoom-panel");
  panel.style.transform = flipTransform(zoom.cell.getBoundingClientRect(), panel.getBoundingClientRect());
  z.classList.add("fade0");
  setTimeout(() => {
    z.classList.add("hidden");
    panel.style.transition = "none";
    panel.style.transform = "";
    zoom.key = null;
  }, 260);
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
  document.querySelectorAll(".cell").forEach((c) => { c.onclick = () => openZoom(c); });
  $("zoom-close").onclick = closeZoom;
  $("zoom").onclick = (e) => { if (e.target === $("zoom")) closeZoom(); };
  document.querySelectorAll("#zoom-range .btn").forEach((b) => {
    b.onclick = () => {
      zoom.range = +b.dataset.s;
      document.querySelectorAll("#zoom-range .btn").forEach((x) => x.classList.toggle("sel", x === b));
      drawZoom();
    };
  });
  const zc = $("zoom-canvas");
  zc.onmousemove = (e) => { zoom.hoverX = e.offsetX; if (zoom.key) drawZoom(); };
  zc.onmouseleave = () => { zoom.hoverX = null; if (zoom.key) drawZoom(); };
  window.addEventListener("resize", () => { if (zoom.key) drawZoom(); });
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
  $("v3v3").oninput = () => { v3v3Dirty = true; $("v3v3-state").textContent = ""; };
  $("v3v3-set").onclick = async () => {
    const j = await post("/api/config", { v3v3: parseFloat($("v3v3").value) });
    if (j && j.ok !== false) {
      v3v3Dirty = false;
      v3v3Sent = j.config.v3v3;
      $("v3v3").value = j.config.v3v3.toFixed(3);
      $("v3v3-state").textContent = `set to ${j.config.v3v3.toFixed(3)} V`;
    }
  };
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
