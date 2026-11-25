import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

function element() {
  return {
    children: [], style: {}, textContent: "", _html: "",
    get innerHTML() { return this._html || this.textContent.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"); },
    set innerHTML(value) { this._html = value; this.children = []; },
    appendChild(child) { this.children.push(child); },
    getAttribute() { return null; },
  };
}

function mobile(fetch) {
  const html = readFileSync(new URL("../app/templates/mobile.html", import.meta.url), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const elements = { mobile: element(), updated: element() };
  const errors = [];
  const context = {
    document: { getElementById: id => elements[id] || null, createElement: element, addEventListener() {} },
    fetch, AbortController, setTimeout: () => 1, clearTimeout() {},
    console: { error: (...args) => errors.push(args) },
  };
  runInNewContext(readFileSync(new URL("../app/static/js/room-temperatures.js", import.meta.url), "utf8"), context);
  runInNewContext(script, context);
  return { context, elements, errors };
}

test("mobile renders latest stored readings regardless of their measurement date", async () => {
  const now = new Date().toISOString();
  const old = new Date(Date.now() - 120 * 60000).toISOString();
  const data = { sensors: [
    { label: "Reporting", type: "am103", updated: now, metric_updated: { co2: now }, readings: { co2: 600 } },
    { label: "Earlier", type: "am103", updated: old, metric_updated: { co2: old }, readings: { co2: 2400 } },
    { label: "Auditorium", type: "am107", updated: now,
      metric_updated: { co2: now, activity: now, illumination: now, tvoc: now, pressure: now },
      readings: { co2: 700, activity: 0, illumination: 350, tvoc: 120, pressure: 1013.2 } },
  ] };
  const app = mobile(async url => ({ ok: true, json: async () => url === "/api/buildings" ? [{ id: 1, name: "Library" }] : data }));
  await app.context.loadDashboard();
  assert.equal(app.errors.length, 0);
  assert.equal(app.elements.mobile.children.length, 1);
  const html = app.elements.mobile.children[0].innerHTML;
  assert.ok(html.includes("Library"));
  assert.ok(html.includes("Poor"));
  assert.ok(!html.includes("<small>"));
  assert.ok(html.includes('sensor-am107'));
  assert.ok(html.includes('PIR activity'));
  assert.ok(html.includes('0 count'));
  assert.ok(html.includes('350 lux'));
  assert.ok(html.includes('120 ppb'));
  assert.ok(html.includes('1013.2 hPa'));
  assert.ok(app.elements.updated.textContent.includes("Dashboard refreshed"));
});

test("mobile shows room temperatures and the server-computed room average", async () => {
  const summary = {
    temperature: { current: 10, aggregation_count: 2 },
    room_temperatures: [
      { label: "Cold room", current: 0, source_count: 1 },
      { label: "<Room B>", current: 20, source_count: 2 },
      { label: "Room C", current: null, source_count: 0 },
    ],
  };
  const app = mobile(async url => ({ ok: true, json: async () =>
    url === "/api/buildings" ? [{ id: 1, name: "SiS" }] :
    url.endsWith("/summary") ? summary : { sensors: [] },
  }));
  await app.context.loadDashboard();
  const html = app.elements.mobile.children[0].innerHTML;
  assert.match(html, /0\.0 °C/);
  assert.match(html, /20\.0 °C/);
  assert.match(html, /10\.0 °C/);
  assert.match(html, /&lt;Room B&gt;/);
  assert.match(html, /No reading/);
  assert.match(html, /2 sensors/);
  assert.match(html, /2 rooms/);
});

test("a failing sensor request leaves its building card visible", async () => {
  const app = mobile(async url => {
    if (url === "/api/buildings") return { ok: true, json: async () => [{ id: 1, name: "Library" }] };
    throw new Error("offline");
  });
  await app.context.loadDashboard();
  assert.equal(app.errors.length, 0);
  assert.ok(app.elements.mobile.children[0].innerHTML.includes("Unable to load sensor data"));
});

test("API timeout aborts an unresponsive request", async () => {
  const callbacks = [];
  const context = {
    AbortController,
    setTimeout: fn => { callbacks.push(fn); return 1; }, clearTimeout() {},
    fetch: (_url, { signal }) => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new Error("aborted")))),
  };
  runInNewContext(readFileSync(new URL("../app/static/js/api-client.js", import.meta.url), "utf8"), context);
  const pending = context.getJSON("/buildings");
  callbacks[0]();
  await assert.rejects(pending, /aborted/);
});

test("missing history values are not converted into zero", () => {
  const context = {};
  runInNewContext(readFileSync(new URL("../app/static/js/api-client.js", import.meta.url), "utf8"), context);
  const points = context.aggregateMetricHistory({ series: [{ metric: "co2", points: [{ time: "2026-10-08T12:00:00Z", value: null }] }] }, "co2");
  assert.equal(points.length, 0);
});

test("charts redraw cached data after rotation and reuse one resize observer", () => {
  const root = { clientWidth: 1200, clientHeight: 500 };
  const observers = [];
  const context = {
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe(target) { assert.equal(target, root); }
    },
  };
  runInNewContext(readFileSync(new URL("../app/static/js/charts/timeSeries.js", import.meta.url), "utf8"), context);
  const drawn = [];
  context.drawTimeSeriesChart = config => drawn.push(config);
  const data = [{ time: "2026-11-01T10:00:00Z", value: 650 }];
  context.renderTimeSeriesChart({ container: root, data, metric: { label: "CO2" }, options: { fitContainer: true } });
  observers[0].callback();
  const count = drawn.length;
  observers[0].callback();
  assert.equal(drawn.length, count);
  root.clientWidth = 650;
  root.clientHeight = 1000;
  observers[0].callback();
  assert.equal(drawn.length, count + 1);
  assert.equal(drawn.at(-1).data, data);
  context.renderTimeSeriesChart({ container: root, data: [], metric: { label: "CO2" } });
  assert.equal(observers.length, 1);
});

test("Samsung URL page loads and refreshes using the published display interval", async () => {
  const html = readFileSync(new URL("../app/templates/display.html", import.meta.url), "utf8");
  const elements = Object.fromEntries(
    [...html.matchAll(/\bid="([^"]+)"/g)].map(([, id]) => [id, element()]),
  );
  elements["display-pulse"].dataset = {};
  const scenes = [...html.matchAll(/class="display-scene(?: active)?"/g)].map(() => ({
    classList: { add() {}, remove() {} },
    setAttribute() {},
  }));
  assert.ok(scenes.length > 0);
  const label = element();
  const scheduled = [];
  const historyRanges = [];
  const co2 = { current: 650, unit: "ppm", change_1h: 20, coverage_24h: 1, source_count: 1 };
  const temperature = { current: 21, unit: "°C", change_1h: 0, coverage_24h: 1, aggregation_count: 2 };
  const energy = { current_kw: 4 };
  const data_quality = {
    sensors_with_readings: 1, registered_sensors: 1, missing_sensors: 0,
    latest_reading: "2026-11-23T15:05:48Z",
  };
  const summary = {
    co2, temperature, energy, data_quality, insights: [],
    buildings: [{
      building: { id: 1, name: "KEH", slug: "keh" },
      co2, temperature, energy, data_quality, recommendations: [],
      room_temperatures: [
        { label: "Room A", current: 20, source_count: 1 },
        { label: "Room B", current: 22, source_count: 1 },
        { label: "Room C", current: null, source_count: 0 },
      ],
    }],
  };
  const context = {
    document: {
      getElementById: id => elements[id] || null,
      createElement: element,
      querySelector: selector => selector === '[data-scene="data-quality"] .scene-label' ? label : null,
      querySelectorAll: selector => selector === ".display-scene" ? scenes : [],
    },
    window: { location: { search: "", origin: "https://display.example.test" } },
    URLSearchParams,
    setInterval: () => 1,
    setTimeout: (callback, milliseconds) => { scheduled.push({ callback, milliseconds }); return 1; },
    getSystemStatus: async () => ({ dashboard_url: "https://display.example.test/overview", display_refresh_seconds: 45 }),
    getCampusSummary: async () => summary,
    getMethodology: async () => ({}),
    getHistory: async (_buildingId, range) => { historyRanges.push(range); return { series: [] }; },
    aggregateMetricHistory: () => [],
    renderTimeSeriesChart() {},
  };
  runInNewContext(readFileSync(new URL("../app/static/js/room-temperatures.js", import.meta.url), "utf8"), context);
  runInNewContext(readFileSync(new URL("../app/static/js/display-pulse.js", import.meta.url), "utf8"), context);

  await context.initDisplayPulse();
  assert.equal(elements["display-source"].textContent, "Sensor readings");
  assert.equal(elements["display-co2"].textContent, "650 ppm");
  assert.match(elements["display-building-grid"].innerHTML, /Room A/);
  assert.match(elements["display-building-grid"].innerHTML, /20\.0 °C/);
  assert.match(elements["display-building-grid"].innerHTML, /Room B/);
  assert.match(elements["display-building-grid"].innerHTML, /22\.0 °C/);
  assert.match(elements["display-building-grid"].innerHTML, /No reading/);
  assert.match(elements["display-building-grid"].innerHTML, /Average of measured rooms:/);
  assert.match(elements["display-temp-context"].textContent, /2 measured rooms/);
  assert.equal(elements["display-pulse"].dataset.preset, "lobby");
  assert.equal(elements["display-dashboard-url"].textContent, "https://display.example.test/overview");
  assert.equal(scheduled[0].milliseconds, 45_000);
  assert.ok(historyRanges.length > 0);
  assert.ok(historyRanges.every(range => range === "1h"));

  co2.current = 900;
  await scheduled.shift().callback();
  assert.equal(elements["display-co2"].textContent, "900 ppm");
  assert.equal(scheduled[0].milliseconds, 45_000);

  co2.current = 650;
  await scheduled.shift().callback();
  assert.equal(elements["display-co2"].textContent, "650 ppm");
  assert.match(elements["scene-campus-summary"].textContent, /Latest average is 650/);
  assert.match(elements["display-updated"].textContent, /Latest measurement:/);
  assert.match(elements["display-map-summary"].textContent, /highest CO2 average/);

  co2.current = null;
  await scheduled.shift().callback();
  assert.equal(elements["display-co2"].textContent, "--");
  assert.match(elements["scene-campus-summary"].textContent, /No CO2 sensor readings/);
  assert.match(elements["display-map-summary"].textContent, /comparison is unavailable/);
});

test("overview recovers after an API outage without losing its page elements", async () => {
  const scheduled = [];
  const historyRanges = [];
  const elements = new Map();
  const getElementById = id => {
    if (!elements.has(id)) {
      const node = element();
      node.querySelector = selector => getElementById(`${id}:${selector}`);
      elements.set(id, node);
    }
    return elements.get(id);
  };
  const metric = { current: null, unit: "ppm", source_count: 1, sample_count: 0 };
  let offline = true;
  const context = {
    document: { getElementById, createElement: element },
    getSystemStatus: async () => { if (offline) throw new Error("offline"); return { display_refresh_seconds: 45 }; },
    getCampusSummary: async () => ({
      co2: metric, temperature: metric, energy: { current_kw: null, method: "Waiting for readings" },
      buildings: [{
        building: { id: 1, name: "KEH" }, co2: metric, temperature: metric,
        energy: { current_kw: null }, recommendations: [],
        data_quality: { sensors_with_readings: 0, registered_sensors: 1 },
      }], insights: [], data_quality: { sensors_with_readings: 0, registered_sensors: 1, latest_reading: null },
    }),
    getMethodology: async () => ({}),
    getHistory: async (_buildingId, range) => { historyRanges.push(range); return { series: [] }; },
    aggregateMetricHistory: () => [], renderTimeSeriesChart() {},
    setTimeout: callback => { scheduled.push(callback); return 1; },
  };
  runInNewContext(readFileSync(new URL("../app/static/js/room-temperatures.js", import.meta.url), "utf8"), context);
  runInNewContext(readFileSync(new URL("../app/static/js/dashboard.js", import.meta.url), "utf8"), context);
  await context.initCampusPulse();
  assert.equal(getElementById("overview-error").hidden, false);
  assert.equal(getElementById("campus-pulse").innerHTML, "");
  offline = false;
  await scheduled.shift()();
  assert.equal(getElementById("overview-error").hidden, true);
  assert.ok(getElementById("campus-status").textContent.includes("CO2"));

  metric.current = 640;
  await scheduled.shift()();
  assert.match(getElementById("campus-status").textContent, /Latest campus CO2 average is 640 ppm/);
  assert.ok(historyRanges.length > 0);
  assert.ok(historyRanges.every(range => range === "1h"));
});
