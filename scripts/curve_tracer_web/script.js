// Adapted from the ESP32-C3 reference implementation's web UI
// (https://github.com/fborello-lambda/solar_panel_curve_tracer, spiffs/
// script.js) - same Chart.js dual-axis I(V)/P(V) chart and unit-toggle
// logic, trimmed for this board:
//
// - No /set-current POST form (this board has no settable current dial).
//   Start Sweep/Release Relay below replace the reference's
//   /start-measurement form.
// - No incremental "have=N" point-count polling protocol: a sweep here is
//   a single bulk read of TRACER_SWEEP_POINTS (20) points, not a stream
//   that grows one point at a time, so /data always returns the whole
//   last sweep and this script just diffs the point count to know when a
//   new sweep landed.
(function () {
  const css = getComputedStyle(document.documentElement);
  const ACCENT = css.getPropertyValue("--accent").trim() || "#ff9800";
  const FG = css.getPropertyValue("--fg").trim() || "#fff8ec";
  const MUTED = css.getPropertyValue("--muted").trim() || "#ffcc99";

  const infoEl = document.getElementById("info");
  const linkStatusEl = document.getElementById("linkStatus");
  const canvas = document.getElementById("chartCanvas");
  const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;

  if (!window.Chart) {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<pre style="color:#f88">Chart.js not found</pre>'
    );
    return;
  }

  const ctx = canvas.getContext("2d");

  const chart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "I(V)",
          data: [],
          parsing: false,
          borderColor: ACCENT,
          pointBackgroundColor: ACCENT,
          pointBorderColor: ACCENT,
          pointRadius: isTouch ? 6 : 4,
          hoverRadius: isTouch ? 10 : 6,
          borderWidth: 2,
          tension: 0.12,
          yAxisID: "y",
        },
        {
          label: "P(V)",
          data: [],
          parsing: false,
          borderColor: "red",
          backgroundColor: "rgba(255,0,0,0.12)",
          pointBackgroundColor: "red",
          pointBorderColor: "red",
          pointRadius: isTouch ? 4 : 2,
          hoverRadius: isTouch ? 8 : 4,
          borderWidth: 2,
          tension: 0.12,
          yAxisID: "p",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "nearest", axis: "xy", intersect: true },
      plugins: {
        legend: { display: true },
        tooltip: {
          enabled: true,
          backgroundColor: "rgba(0,0,0,0.8)",
          titleColor: FG,
          bodyColor: FG,
          callbacks: {
            title: (items) => "V: " + (items[0]?.raw?.x ?? ""),
            label: (ctx) => {
              if (ctx.dataset.label === "I(V)") {
                return (
                  "I: " +
                  Number(ctx.raw.y).toFixed(3) +
                  (unitIsMilli ? " mA" : " A")
                );
              }
              return (
                "P: " +
                Number(ctx.raw.y).toFixed(3) +
                (unitIsMilli ? " mW" : " W")
              );
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: 25,
          title: { display: true, text: "Voltage [V]", color: MUTED },
          ticks: { color: MUTED },
        },
        y: {
          position: "left",
          min: 0,
          max: 10,
          title: { display: true, text: "Current [mA]", color: ACCENT },
          ticks: { color: ACCENT },
        },
        p: {
          id: "p",
          position: "right",
          title: { display: true, text: "Power [mW]", color: "red" },
          ticks: { color: "red" },
        },
      },
    },
  });

  const autoBtn = document.getElementById("autoBtn");
  const autoPowerBtn = document.getElementById("autoPowerBtn");

  // true = chart data in mA, false = in A. The server always sends mA.
  let unitIsMilli = true;
  const unitBtn = document.getElementById("unitBtn");

  function autoScale() {
    delete chart.options.scales.x.min;
    delete chart.options.scales.x.max;
    delete chart.options.scales.y.min;
    delete chart.options.scales.y.max;
    delete chart.options.scales.p.min;
    delete chart.options.scales.p.max;
    chart.update("none");
  }
  autoBtn.addEventListener("click", autoScale);

  function autoScalePower() {
    delete chart.options.scales.p.min;
    delete chart.options.scales.p.max;
    chart.update("none");
  }
  autoPowerBtn.addEventListener("click", autoScalePower);

  function toggleUnits() {
    const data = chart.data.datasets[0].data;
    const oldIsMilli = unitIsMilli;
    const newIsMilli = !oldIsMilli;

    if (data && data.length) {
      for (let i = 0; i < data.length; i++) {
        data[i] = {
          x: data[i].x,
          y: oldIsMilli ? data[i].y / 1000.0 : data[i].y * 1000.0,
        };
      }
    }

    const cur = chart.data.datasets[0].data || [];
    chart.data.datasets[1].data = cur.map((pt) => ({ x: pt.x, y: pt.x * pt.y }));

    if (newIsMilli) {
      chart.options.scales.y.title.text = "Current [mA]";
      if (typeof chart.options.scales.p.min === "number") chart.options.scales.p.min *= 1000.0;
      if (typeof chart.options.scales.p.max === "number") chart.options.scales.p.max *= 1000.0;
      chart.options.scales.p.title.text = "Power [mW]";
    } else {
      chart.options.scales.y.title.text = "Current [A]";
      if (typeof chart.options.scales.p.min === "number") chart.options.scales.p.min /= 1000.0;
      if (typeof chart.options.scales.p.max === "number") chart.options.scales.p.max /= 1000.0;
      chart.options.scales.p.title.text = "Power [W]";
    }

    unitIsMilli = newIsMilli;
    chart.update("none");
  }
  unitBtn.addEventListener("click", toggleUnits);

  function maybeConvertIncoming(arr) {
    if (!unitIsMilli) {
      for (let i = 0; i < arr.length; i++) arr[i].y = arr[i].y / 1000.0;
    }
  }

  // Start Sweep / Release Relay: empty-body POSTs, 204 on success. No
  // response to parse - the tick() polling loop below already picks up a
  // new sweep result once one lands.
  async function postCommand(path, btn) {
    btn.disabled = true;
    try {
      const r = await fetch(path, { method: "POST" });
      if (!r.ok) throw new Error("HTTP " + r.status);
    } catch (e) {
      console.error(path + " failed", e);
    } finally {
      btn.disabled = false;
    }
  }
  document
    .getElementById("startSweepBtn")
    .addEventListener("click", (e) => postCommand("/start-sweep", e.target));
  document
    .getElementById("releaseRelayBtn")
    .addEventListener("click", (e) => postCommand("/release-relay", e.target));

  const mpptCurrentEl = document.getElementById("mpptCurrent");
  const mpptVoltageEl = document.getElementById("mpptVoltage");

  function refreshMPPT(data) {
    if (!data || !data.length) {
      mpptCurrentEl.textContent = "MPPT Current: --";
      mpptVoltageEl.textContent = "MPPT Voltage: --";
      return;
    }
    const best = [...data].sort((a, b) => b.x * b.y - a.x * a.y)[0];
    const currentDisplay = unitIsMilli
      ? `${best.y.toFixed(3)} mA`
      : `${best.y.toFixed(3)} A`;
    mpptCurrentEl.textContent = `MPPT Current: ${currentDisplay}`;
    mpptVoltageEl.textContent = `MPPT Voltage: ${best.x.toFixed(3)} V`;
  }

  // Polling: /data always returns the full last sweep (or [] if none has
  // landed yet) - a sweep is at most TRACER_SWEEP_POINTS (20) points, so
  // there is no benefit to the reference implementation's incremental
  // have=N fetch, only extra state to get wrong.
  let lastCount = -1;
  const POLL_MS = isTouch ? 3000 : 2000;

  async function tick() {
    try {
      const r = await fetch("/data", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const payload = await r.json();
      const arr = Array.isArray(payload.points) ? payload.points : [];
      linkStatusEl.textContent = "Link: " + (payload.link || "--");

      if (arr.length !== lastCount) {
        maybeConvertIncoming(arr);
        chart.data.datasets[0].data = arr;
        chart.data.datasets[1].data = arr.map((pt) => ({ x: pt.x, y: pt.x * pt.y }));
        infoEl.textContent = "points: " + arr.length;
        autoScale();
        autoScalePower();
        refreshMPPT(chart.data.datasets[0].data);
        lastCount = arr.length;
      }
    } catch (e) {
      console.error("tick failed", e);
      linkStatusEl.textContent = "Link: error";
    } finally {
      setTimeout(tick, POLL_MS);
    }
  }

  tick();

  window.addEventListener(
    "orientationchange",
    () => setTimeout(() => chart.resize(), 250),
    { passive: true }
  );
})();
