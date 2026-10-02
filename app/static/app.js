"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  files: [null, null],
  result: null,
  selected: 1,
  view: "transmission",
  busy: false,
  dirty: false,
  traces: [],
};
const fmt = (v, n = 2) => (v == null ? "—" : Number(v).toFixed(n));
const esc = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const statuses = {
  PASS: "PASS",
  FAIL: "FAIL",
  INCOMPLETE: "НЕПОЛНЫЕ ДАННЫЕ",
  NOT_EVALUATED: "НЕТ ДАННЫХ",
};
const colors = ["#4ad7c5", "#f3a078", "#b1a6f4", "#80b5eb"];
const badge = (s) => `<span class="badge ${s}">${statuses[s]}</span>`;

function setBusy(busy) {
  state.busy = busy;
  for (const id of ["apply", "demo", "remove-b"]) $(id).disabled = busy;
  for (const id of ["file-a", "file-b"]) $(id).disabled = busy;
  $("export").disabled = busy || state.dirty || !state.result;
  $("connection").textContent = busy
    ? "Обработка данных…"
    : state.result
      ? "Локальный анализатор готов"
      : "Нет связи с сервером";
}
function showError(message = "") {
  $("error").textContent = message;
  $("error").hidden = !message;
}
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = error.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e) => e.msg).join("; ")
          : `Ошибка сервера ${response.status}`,
    );
  }
  return response;
}
function formRequirements() {
  return Object.fromEntries(
    [...new FormData($("requirements"))].map(([k, v]) => [k, Number(v)]),
  );
}
function body() {
  return {
    dataset_ids: state.files.filter(Boolean).map((f) => f.id),
    requirements: formRequirements(),
  };
}
function fileSlots() {
  state.files.forEach((file, i) => {
    const suffix = i === 0 ? "a" : "b";
    $("name-" + suffix).textContent = file ? file.name : "Файл не выбран";
    $("detail-" + suffix).textContent = file
      ? `${file.points.toLocaleString("ru-RU")} точек · ${fmt(file.range_ghz[0], 2)}–${fmt(file.range_ghz[1], 2)} ГГц · ${file.reference_ohm} Ω`
      : "Можно анализировать один образец";
  });
}
async function analyze() {
  const response = await api("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body()),
  });
  state.result = await response.json();
  state.selected = Math.min(state.selected, state.result.datasets.length - 1);
  state.dirty = false;
  $("dirty-note").hidden = true;
  render();
}
async function demo() {
  if (state.busy) return;
  setBusy(true);
  showError();
  try {
    const data = await (await api("/api/demo")).json();
    state.files = data.datasets;
    for (const [key, value] of Object.entries(data.requirements))
      $("requirements").elements.namedItem(key).value = value;
    state.selected = 1;
    fileSlots();
    await analyze();
  } catch (error) {
    showError(error.message);
    $("connection").textContent = "Нет связи с сервером";
  } finally {
    setBusy(false);
  }
}
async function upload(file, slot) {
  if (!file || state.busy) return;
  setBusy(true);
  showError();
  const previous = [...state.files],
    previousResult = state.result,
    previousSelected = state.selected;
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error("Файл больше 2 МиБ.");
    const metadata = await (
      await api(`/api/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      })
    ).json();
    state.files[slot] = metadata;
    state.selected = slot;
    await analyze();
    fileSlots();
  } catch (error) {
    state.files = previous;
    state.result = previousResult;
    state.selected = previousSelected;
    showError(error.message);
  } finally {
    setBusy(false);
    $(slot === 0 ? "file-a" : "file-b").value = "";
  }
}
function render() {
  const { datasets } = state.result;
  const selected = datasets[state.selected];
  const allSynthetic = datasets.every((d) => d.source === "synthetic");
  $("source-notice").innerHTML =
    `<span class="source-icon">◈</span><div><strong>${allSynthetic ? "Синтетические данные · модель LC-фильтра" : "Загруженные данные · происхождение указано для каждого файла"}</strong><span>${allSynthetic ? "Файлы рассчитаны из электрической цепи. Это не измерения реального прибора." : "Анализатор проверяет содержимое файла. Источник, калибровка и достоверность измерений не подтверждаются."}</span></div><span class="notice-tag">${allSynthetic ? "DEMO LAB" : "LOCAL FILES"}</span>`;
  $("comparison").innerHTML = datasets
    .map((d, i) => {
      const failures = d.checks.filter((c) => c.status === "FAIL").length;
      const text =
        d.verdict === "PASS"
          ? "Все 4 требования выполнены"
          : d.verdict === "INCOMPLETE"
            ? `Часть требований не проверена${failures ? `; нарушений: ${failures}` : ""}`
            : `Нарушено требований: ${failures} из 4`;
      return `<button class="sample-card ${i === state.selected ? "selected" : ""}" data-select="${i}" aria-pressed="${i === state.selected}"><div class="sample-card-top"><span class="series-dot ${i === 0 ? "a" : "b"}"></span>ОБРАЗЕЦ ${i === 0 ? "A" : "B"}${badge(d.verdict)}</div><h3>${esc(d.name)}</h3><p>${d.source === "synthetic" ? "Модель LC-цепи · синтетический файл" : "Загруженный файл · источник не подтверждён"}</p><div class="sample-description">${text}</div></button>`;
    })
    .join("");
  $("comparison")
    .querySelectorAll("[data-select]")
    .forEach((b) =>
      b.addEventListener("click", () => {
        state.selected = Number(b.dataset.select);
        render();
      }),
    );
  const delay = selected.delay_range_ns;
  $("metrics").innerHTML = [
    [
      "Пик передачи",
      `${fmt(selected.peak_frequency_ghz, 3)} <small>ГГц</small>`,
      `S21 = ${fmt(selected.peak_s21_db)} дБ`,
    ],
    [
      "Полоса −3 дБ от пика",
      `${fmt(selected.bandwidth.width_mhz, 1)} <small>МГц</small>`,
      selected.bandwidth.reason ||
        `${fmt(selected.bandwidth.lower_ghz, 3)}–${fmt(selected.bandwidth.upper_ghz, 3)} ГГц`,
    ],
    [
      "Задержка в рабочей полосе",
      `${delay ? fmt(delay[0]) + "–" + fmt(delay[1]) : "—"} <small>нс</small>`,
      "По развёрнутой фазе S21 · справочно",
    ],
  ]
    .map(
      ([label, value, note]) =>
        `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-note">${esc(note)}</div></div>`,
    )
    .join("");
  $("selected-name").textContent = selected.name;
  $("checks").innerHTML = selected.checks
    .map(
      (c) =>
        `<tr><td><span class="req-code">${c.code}</span><strong>${esc(c.label)}</strong><small>${fmt(c.start_ghz, 2)}–${fmt(c.end_ghz, 2)} ГГц · ${c.native_points} точек</small></td><td>${c.sense === "max" ? "≤" : "≥"} ${fmt(c.limit, 1)} дБ</td><td>${fmt(c.actual)}${c.actual == null ? "" : " дБ"}<small>${c.actual == null ? esc(c.reason) : fmt(c.worst_frequency_ghz, 4) + " ГГц"}</small></td><td class="${c.margin_db >= 0 ? "margin-positive" : "margin-negative"}">${c.margin_db == null ? "—" : (c.margin_db >= 0 ? "+" : "") + fmt(c.margin_db) + " дБ"}</td><td>${badge(c.status)}</td></tr>`,
    )
    .join("");
  const explanation = {
    PASS: "Все требования выполнены на доступной сетке частот. Это заключение по данным файла, без оценки неопределённости измерений.",
    FAIL: "Есть подтверждённые нарушения. Выше показаны худшая частота и величина запаса: отрицательное значение указывает на выход за допуск.",
    INCOMPLETE:
      "Не хватает диапазона или точек для части требований. Полный PASS/FAIL не присваивается; уже найденные нарушения остаются видны.",
  };
  $("explanation").textContent = explanation[selected.verdict];
  $("evidence").innerHTML = datasets
    .map(
      (d, i) =>
        `<div class="evidence-file"><strong>${i === 0 ? "A" : "B"} / ${esc(d.name)}</strong><p>${d.points.toLocaleString("ru-RU")} исходных точек · шаг до ${fmt(d.max_step_mhz, 2)} МГц · ${d.format} · ${d.reference_ohm} Ω</p><code>SHA-256 ${d.sha256}</code><a href="/api/datasets/${encodeURIComponent(d.id)}/csv">↓ CSV всех частотных точек</a></div>`,
    )
    .join("");
  $("warnings").innerHTML = selected.warnings
    .map((w) => `<div class="warning">${esc(w)}</div>`)
    .join("");
  drawChart();
}
function drawChart() {
  const datasets = state.result.datasets,
    selected = datasets[state.selected],
    req = state.result.requirements;
  let traces;
  if (state.view === "transmission" || state.view === "delay")
    traces = datasets.map((d, i) => ({
      label: `${i === 0 ? "A" : "B"} / ${state.view === "delay" ? "τ" : "S21"}`,
      f: d.plot.frequency_ghz,
      y: state.view === "delay" ? d.plot.delay_ns : d.plot.db.S21,
      color: colors[i],
    }));
  else {
    const keys =
      state.view === "all" ? ["S21", "S11", "S12", "S22"] : ["S11", "S22"];
    traces = keys.map((key, i) => ({
      label: `${state.selected === 0 ? "A" : "B"} / ${key}`,
      f: selected.plot.frequency_ghz,
      y: selected.plot.db[key],
      color: colors[i],
      dash: key === "S12" || key === "S22",
    }));
  }
  state.traces = traces;
  const delay = state.view === "delay";
  const lo = Math.min(...traces.map((t) => t.f[0])),
    hi = Math.max(...traces.map((t) => t.f[t.f.length - 1]));
  const finite = traces.flatMap((t) => t.y.filter((v) => v !== null));
  let top = delay ? Math.max(1, ...finite) : Math.max(3, ...finite);
  let bottom = delay
    ? Math.min(0, ...finite)
    : Math.max(-100, Math.min(-40, ...finite));
  if (delay) {
    const pad = (top - bottom) * 0.12;
    top += pad;
    bottom -= pad;
  }
  const x = (f) => 62 + ((f - lo) / (hi - lo)) * 908;
  const y = (v) =>
    20 + ((top - Math.max(bottom, Math.min(top, v))) / (top - bottom)) * 305;
  state.axes = { lo, hi, x, y };
  let svg =
    '<defs><clipPath id="plot-clip"><rect x="62" y="20" width="908" height="305"/></clipPath></defs>';
  for (const [start, end, fill] of [
    [req.low_stop_start_ghz, req.low_stop_end_ghz, "#714e3328"],
    [req.pass_start_ghz, req.pass_end_ghz, "#36786635"],
    [req.high_stop_start_ghz, req.high_stop_end_ghz, "#714e3328"],
  ]) {
    const left = Math.max(start, lo),
      right = Math.min(end, hi);
    if (right > left)
      svg += `<rect x="${x(left)}" y="20" width="${x(right) - x(left)}" height="305" fill="${fill}"/>`;
  }
  for (let i = 0; i <= 5; i++) {
    const v = bottom + ((top - bottom) * i) / 5;
    svg += `<path d="M62 ${y(v)}H970" stroke="#35515f" stroke-opacity=".6"/><text x="51" y="${y(v) + 4}" text-anchor="end" fill="#819da9" font-size="10">${fmt(v, 1)}</text>`;
  }
  for (let i = 0; i <= 6; i++) {
    const f = lo + ((hi - lo) * i) / 6;
    svg += `<path d="M${x(f)} 20V325" stroke="#35515f" stroke-opacity=".35"/><text x="${x(f)}" y="349" text-anchor="middle" fill="#819da9" font-size="10">${fmt(f, 3)}</text>`;
  }
  const threshold =
    state.view === "return" ? -req.min_return_loss_db : -req.max_loss_db;
  if (!delay) {
    const start = Math.max(req.pass_start_ghz, lo),
      end = Math.min(req.pass_end_ghz, hi);
    if (start < end)
      svg += `<path d="M${x(start)} ${y(threshold)}H${x(end)}" stroke="#7eaa92" stroke-dasharray="4 4"/><text x="${x(end) + 5}" y="${y(threshold) + 12}" fill="#88b8a0" font-size="9">${fmt(threshold, 0)} дБ</text>`;
  }
  if (state.view === "transmission")
    for (const [start, end] of [
      [req.low_stop_start_ghz, req.low_stop_end_ghz],
      [req.high_stop_start_ghz, req.high_stop_end_ghz],
    ]) {
      const a = Math.max(start, lo),
        b = Math.min(end, hi);
      if (a < b)
        svg += `<path d="M${x(a)} ${y(-req.min_attenuation_db)}H${x(b)}" stroke="#c49067" stroke-dasharray="4 4"/>`;
    }
  for (const trace of traces) {
    let path = "",
      pen = false;
    trace.f.forEach((f, i) => {
      const v = trace.y[i];
      if (v === null) {
        pen = false;
        return;
      }
      path += `${pen ? "L" : "M"}${x(f).toFixed(2)} ${y(v).toFixed(2)} `;
      pen = true;
    });
    svg += `<path d="${path}" fill="none" stroke="${trace.color}" stroke-width="2" ${trace.dash ? 'stroke-dasharray="6 4"' : ""} clip-path="url(#plot-clip)"/>`;
  }
  svg += `<text x="14" y="14" fill="#7d9ba9" font-size="10">${delay ? "нс" : "дБ"}</text><text x="970" y="377" text-anchor="end" fill="#7d9ba9" font-size="10">Частота / ГГц</text><path id="crosshair" d="" stroke="#adbdc5" stroke-dasharray="3 4" stroke-opacity=".5"/>`;
  $("chart").innerHTML = svg;
  $("chart-title").textContent = {
    transmission: "Передача S21",
    return: "Согласование S11 / S22",
    all: "Четыре S-параметра",
    delay: "Групповая задержка S21",
  }[state.view];
  $("legend").innerHTML = traces
    .map((t) => `<span><i style="background:${t.color}"></i>${t.label}</span>`)
    .join("");
  $("plot-note").textContent =
    `График: до 2 005 точек / расчёты: все исходные${delay ? " · |S21| > −60 дБ" : ""}`;
  $("tooltip").hidden = true;
}
$("chart").addEventListener("pointermove", (event) => {
  if (!state.axes) return;
  const rect = $("chart").getBoundingClientRect(),
    local = ((event.clientX - rect.left) / rect.width) * 1000;
  if (local < 62 || local > 970) {
    $("tooltip").hidden = true;
    return;
  }
  const f =
    state.axes.lo + ((local - 62) / 908) * (state.axes.hi - state.axes.lo);
  const rows = state.traces.map((t) => {
    if (f < t.f[0] || f > t.f[t.f.length - 1])
      return `<div>${t.label}: вне диапазона</div>`;
    let low = 0,
      high = t.f.length - 1;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (t.f[middle] < f) low = middle + 1;
      else high = middle;
    }
    const i =
      low > 0 && Math.abs(t.f[low - 1] - f) < Math.abs(t.f[low] - f)
        ? low - 1
        : low;
    return `<div>${t.label}: ${fmt(t.y[i])} ${state.view === "delay" ? "нс" : "дБ"}<br><span style="color:#8196a1">точка ${fmt(t.f[i], 4)} ГГц</span></div>`;
  });
  $("crosshair").setAttribute("d", `M${local} 20V325`);
  $("tooltip").innerHTML = `<strong>${fmt(f, 4)} ГГц</strong>${rows.join("")}`;
  $("tooltip").hidden = false;
  const wrap = $("chart").parentElement.getBoundingClientRect();
  $("tooltip").style.left =
    `${Math.min(Math.max(12, event.clientX - wrap.left + 15), Math.max(12, wrap.width - $("tooltip").offsetWidth - 12))}px`;
  $("tooltip").style.top = "18px";
});
$("chart").addEventListener("pointerleave", () => {
  $("tooltip").hidden = true;
  if ($("crosshair")) $("crosshair").setAttribute("d", "");
});
document.querySelectorAll("[data-view]").forEach((button) =>
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    document
      .querySelectorAll("[data-view]")
      .forEach((b) => b.classList.toggle("active", b === button));
    if (state.result) drawChart();
  }),
);
$("requirements").addEventListener("input", () => {
  state.dirty = true;
  $("dirty-note").hidden = false;
  $("export").disabled = true;
});
$("requirements").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  showError();
  try {
    await analyze();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
});
$("demo").addEventListener("click", demo);
$("file-a").addEventListener("change", (e) => upload(e.target.files[0], 0));
$("file-b").addEventListener("change", (e) => upload(e.target.files[0], 1));
$("remove-b").addEventListener("click", async () => {
  if (!state.files[1] || state.busy) return;
  setBusy(true);
  showError();
  const previous = [...state.files],
    previousSelected = state.selected;
  try {
    state.files[1] = null;
    state.selected = 0;
    await analyze();
    fileSlots();
  } catch (error) {
    state.files = previous;
    state.selected = previousSelected;
    showError(error.message);
  } finally {
    setBusy(false);
  }
});
$("export").addEventListener("click", async () => {
  if (state.busy || state.dirty) return;
  setBusy(true);
  showError();
  try {
    const response = await api("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_ids: state.result.datasets.map((d) => d.id),
        requirements: state.result.requirements,
      }),
    });
    const url = URL.createObjectURL(await response.blob()),
      a = document.createElement("a");
    a.href = url;
    a.download = "rf-analysis-report.html";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
});
demo();
