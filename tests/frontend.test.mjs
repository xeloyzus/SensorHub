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
  runInNewContext(script, context);
  return { context, elements, errors };
}

test("mobile renders readings without a scope error and excludes stale CO2 from its badge", async () => {
  const now = new Date().toISOString();
  const old = new Date(Date.now() - 120 * 60000).toISOString();
  const data = { sensors: [
    { label: "Fresh", type: "am103", updated: now, metric_updated: { co2: now }, readings: { co2: 600 } },
    { label: "Stale", type: "am103", updated: old, metric_updated: { co2: old }, readings: { co2: 2400 } },
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
  assert.ok(html.includes("Good"));
  assert.ok(html.includes("<small>Stale</small>"));
  assert.ok(html.includes('sensor-am107'));
  assert.ok(html.includes('PIR activity'));
  assert.ok(html.includes('0 count'));
  assert.ok(html.includes('350 lux'));
  assert.ok(html.includes('120 ppb'));
  assert.ok(html.includes('1013.2 hPa'));
  assert.ok(app.elements.updated.textContent.includes("Dashboard refreshed"));
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
  const co2 = { current: 650, unit: "ppm", change_1h: 20, coverage_24h: 1, source_count: 1 };
  const temperature = { current: 21, unit: "°C", change_1h: 0, coverage_24h: 1 };
  const energy = { current_kw: 4 };
  const data_quality = {
    active_sensors: 1, stale_sensors: 0, missing_sensors: 0,
    freshness: { status: "current", description: "Latest reading is current." },
  };
  const summary = {
    co2, temperature, energy, data_quality, insights: [],
    buildings: [{
      building: { id: 1, name: "KEH", slug: "keh" },
      co2, temperature, energy, data_quality, recommendations: [],
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
    getHistory: async () => ({ series: [] }),
    aggregateMetricHistory: () => [],
    renderTimeSeriesChart() {},
  };
  runInNewContext(readFileSync(new URL("../app/static/js/display-pulse.js", import.meta.url), "utf8"), context);

  await context.initDisplayPulse();
  assert.equal(elements["display-source"].textContent, "Sensor readings");
  assert.equal(elements["display-co2"].textContent, "650 ppm");
  assert.equal(elements["display-pulse"].dataset.preset, "lobby");
  assert.equal(elements["display-dashboard-url"].textContent, "https://display.example.test/overview");
  assert.equal(scheduled[0].milliseconds, 45_000);

  co2.current = 900;
  await scheduled.shift().callback();
  assert.equal(elements["display-co2"].textContent, "900 ppm");
  assert.equal(scheduled[0].milliseconds, 45_000);
});

test("overview recovers after an API outage without losing its page elements", async () => {
  const scheduled = [];
  const elements = new Map();
  const getElementById = id => {
    if (!elements.has(id)) {
      const node = element();
      node.querySelector = selector => getElementById(`${id}:${selector}`);
      elements.set(id, node);
    }
    return elements.get(id);
  };
  const metric = { current: null, sample_count: 0 };
  let offline = true;
  const context = {
    document: { getElementById, createElement: element },
    getSystemStatus: async () => { if (offline) throw new Error("offline"); return { display_refresh_seconds: 45 }; },
    getCampusSummary: async () => ({
      co2: metric, temperature: metric, energy: { current_kw: null, method: "Waiting for readings" },
      buildings: [], insights: [], data_quality: { freshness: { status: "unknown", description: "No readings yet" } },
    }),
    getMethodology: async () => ({}),
    aggregateMetricHistory: () => [], renderTimeSeriesChart() {},
    setTimeout: callback => { scheduled.push(callback); return 1; },
  };
  runInNewContext(readFileSync(new URL("../app/static/js/dashboard.js", import.meta.url), "utf8"), context);
  await context.initCampusPulse();
  assert.equal(getElementById("overview-error").hidden, false);
  assert.equal(getElementById("campus-pulse").innerHTML, "");
  offline = false;
  await scheduled.shift()();
  assert.equal(getElementById("overview-error").hidden, true);
  assert.ok(getElementById("campus-status").textContent.includes("CO2"));
});
