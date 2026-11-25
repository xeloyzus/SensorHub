const DISPLAY_DEFAULT_SCENE_MS = 12_000;
const DISPLAY_REFRESH_MS = 60_000;
const DISPLAY_PRESETS = {
  lobby: { sceneMs: 12_000, density: "balanced" },
  hallway: { sceneMs: 9_000, density: "glance" },
  "small-screen": { sceneMs: 14_000, density: "compact" },
};

function displayConfig() {
  const params = new URLSearchParams(window.location.search);
  const presetName = params.get("preset") || "lobby";
  const preset = DISPLAY_PRESETS[presetName] || DISPLAY_PRESETS.lobby;
  const sceneMs = Number(params.get("scene_ms")) || preset.sceneMs || DISPLAY_DEFAULT_SCENE_MS;
  return {
    presetName,
    sceneMs,
    density: preset.density,
    building: params.get("building") || params.get("location") || "",
  };
}

function formatNumber(value, decimals = 0) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString([], {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  });
}

function metricValue(metric, decimals = 0) {
  const value = metric?.current;
  if (value == null) return "--";
  return `${formatNumber(value, decimals)} ${metric.unit}`;
}

function metricTrend(metric) {
  if (!metric || metric.change_1h == null) return "Trend unavailable";
  const decimals = metric.unit === "°C" ? 1 : 0;
  return `${metric.change_1h >= 0 ? "+" : ""}${formatNumber(metric.change_1h, decimals)} ${metric.unit} in 1 h`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function refreshIntervalMs(status) {
  const seconds = Number(status && status.display_refresh_seconds);
  return Number.isFinite(seconds) && seconds >= 10 ? seconds * 1000 : DISPLAY_REFRESH_MS;
}

function renderRuntimeStatus(status) {
  const source = document.getElementById("display-source");
  if (!source || !status) return;
  source.textContent = "Sensor readings";
  source.className = "live";
}

function renderDisplayUnavailable(error, status) {
  document.getElementById("display-pulse").dataset.state = "unavailable";
  for (const id of ["display-co2", "display-temp", "display-energy"]) {
    document.getElementById(id).textContent = "--";
  }
  document.getElementById("display-connection").textContent = "Data unavailable";
  document.getElementById("display-connection").className = "connection-error";
  document.getElementById("display-confidence").textContent = "Coverage --";
  document.getElementById("scene-campus-summary").textContent =
    "Sensor readings are temporarily unavailable. Reconnecting automatically.";
  document.getElementById("display-co2-context").textContent = "Waiting for the connection to recover";
  document.getElementById("display-temp-context").textContent = "Readings will update when the connection returns";
  document.getElementById("display-chart-summary").textContent = "No live chart can be drawn until history data is available.";
  document.getElementById("display-quality-summary").textContent =
    "No current readings are available from the configured data source.";
  document.getElementById("display-updated").textContent = "Latest reading unavailable.";
}

function coveragePercent(metric) {
  return formatNumber((metric?.coverage_24h || 0) * 100);
}

function buildingMatches(building, query) {
  if (!query) return false;
  const needle = query.toLowerCase();
  return (
    String(building.building.id) === needle ||
    building.building.slug.toLowerCase() === needle ||
    building.building.name.toLowerCase().includes(needle)
  );
}

function pickLocalBuilding(summary, config) {
  return (
    summary.buildings.find((building) => buildingMatches(building, config.building)) ||
    summary.buildings
      .filter((building) => building.co2.current != null)
      .sort((a, b) => (b.co2.current ?? 0) - (a.co2.current ?? 0))[0] ||
    summary.buildings[0]
  );
}

function co2StatusSentence(metric, label = "Campus") {
  if (!metric || metric.current == null) return `${label} CO2 is unavailable.`;
  const trend =
    metric.change_1h == null
      ? "with no reliable one-hour trend yet"
      : metric.change_1h > 25
        ? "and rising"
        : metric.change_1h < -25
          ? "and falling"
          : "and stable";
  if (metric.current >= 1000) return `${label} CO2 is elevated ${trend}.`;
  if (metric.current >= 800) return `${label} CO2 is moderate ${trend}.`;
  return `${label} CO2 is low ${trend}.`;
}

function confidenceSentence(summary) {
  const quality = summary.data_quality;
  return `${quality.sensors_with_readings} of ${quality.registered_sensors} sensors have stored readings · ${coveragePercent(summary.co2)}% CO2 coverage over 24 hours.`;
}

function updateClock() {
  document.getElementById("display-clock").textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function updateDashboardUrl(status) {
  const target = document.getElementById("display-dashboard-url");
  if (target) {
    const url = status?.dashboard_url || target.getAttribute("href") || `${window.location.origin}/overview`;
    target.textContent = url;
    target.href = url;
  }
}

function renderDisplaySummary(summary) {
  document.getElementById("display-connection").textContent = "Connected";
  document.getElementById("display-connection").className = "";
  document.getElementById("display-confidence").textContent =
    `${summary.data_quality.sensors_with_readings} sensors with readings · ${coveragePercent(summary.co2)}% coverage`;
  document.getElementById("display-updated").textContent = summary.data_quality.latest_reading
    ? `Latest measurement: ${new Date(summary.data_quality.latest_reading).toLocaleString()}`
    : "No measurements available";
  document.getElementById("scene-campus-summary").textContent = summary.co2.current != null
    ? `${co2StatusSentence(summary.co2)} Latest average is ${formatNumber(summary.co2.current)} ppm across ${summary.co2.source_count} air sensors with readings.`
    : "No CO2 sensor readings have been received yet.";

  document.getElementById("display-co2").textContent = metricValue(summary.co2);
  document.getElementById("display-co2-context").textContent =
    `${metricTrend(summary.co2)} · ${formatNumber(summary.co2.coverage_24h * 100)}% 24 h coverage`;
  document.getElementById("display-temp").textContent = metricValue(summary.temperature, 1);
  document.getElementById("display-temp-context").textContent =
    `Average of ${summary.temperature.aggregation_count || 0} measured rooms · equal weight per room`;
  document.getElementById("display-energy").textContent =
    summary.energy.current_kw == null ? "--" : `${formatNumber(summary.energy.current_kw, 1)} kW`;
}

function renderLocalFocus(summary, config) {
  const building = pickLocalBuilding(summary, config);
  if (!building) return;

  const isConfigured = Boolean(config.building);
  document.getElementById("scene-local-title").textContent = isConfigured
    ? "This building"
    : "Highest CO2 average";
  document.getElementById("display-local-summary").textContent =
    `${co2StatusSentence(building.co2, building.building.name)} Latest average is ${metricValue(building.co2)}.`;

  const recommendation = building.recommendations[0];
  document.getElementById("display-local-card").innerHTML = `
    <article class="display-focus-card">
      <h3>${escapeHtml(building.building.name)}</h3>
      <div class="display-focus-values">
        <strong>${metricValue(building.co2)}</strong>
        <span>${escapeHtml(metricTrend(building.co2))}</span>
      </div>
      ${roomTemperaturesHtml(building)}
      <p>${recommendation ? escapeHtml(recommendation.verification) : "No action suggested right now."}</p>
    </article>
  `;
}

function renderDisplayBuildings(summary) {
  const grid = document.getElementById("display-building-grid");
  grid.innerHTML = summary.buildings
    .map((building) => {
      const recommendation = building.recommendations[0];
      const action = recommendation
        ? `Possible action: ${recommendation.verification}`
        : "";
      const co2Context = `${formatNumber(building.co2.coverage_24h * 100)}% 24 h coverage`;
      return `
        <article class="display-building-card">
          <div>
            <h3>${escapeHtml(building.building.name)}</h3>
          </div>
          <div class="display-building-values">
            <span>CO2<strong>${metricValue(building.co2)}</strong></span>
            <span>Energy<strong>${building.energy.current_kw == null ? "--" : `${formatNumber(building.energy.current_kw, 1)} kW`}</strong></span>
          </div>
          ${roomTemperaturesHtml(building)}
          <p>${escapeHtml(co2Context)}</p>
          ${action ? `<p>${escapeHtml(action)}</p>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderCampusMap(summary) {
  const buildings = [...summary.buildings]
    .filter((building) => building.co2.current != null)
    .sort((a, b) => (b.co2.current ?? 0) - (a.co2.current ?? 0));
  const highest = buildings[0];
  document.getElementById("display-map-summary").textContent = highest
    ? `${highest.building.name} has the highest CO2 average in the latest readings.`
    : "Building comparison is unavailable until CO2 readings arrive.";

  const max = Math.max(...buildings.map((building) => building.co2.current ?? 0), 1);
  document.getElementById("display-campus-map").innerHTML = buildings
    .map((building, index) => {
      const value = building.co2.current;
      const level = Math.max(18, Math.round(((value || 0) / max) * 100));
      const tone = value >= 1000 ? "attention" : value >= 800 ? "watch" : "good";
      return `
        <article class="display-map-building ${tone}">
          <div class="display-map-bar" style="height: ${level}%"></div>
          <span>${index + 1}</span>
          <h3>${escapeHtml(building.building.name)}</h3>
          <strong>${metricValue(building.co2)}</strong>
          <em>Latest stored average</em>
        </article>
      `;
    })
    .join("");
}

function renderDataQuality(summary) {
  const quality = summary.data_quality;
  const title = document.getElementById("scene-quality-title");
  const label = document.querySelector('[data-scene="data-quality"] .scene-label');
  label.textContent = "Sensor coverage";
  title.textContent = "Available measurements";

  document.getElementById("display-quality-summary").textContent = confidenceSentence(summary);
  document.getElementById("display-quality-list").innerHTML = `
    <span><strong>${quality.registered_sensors}</strong> registered sensors</span>
    <span><strong>${quality.sensors_with_readings}</strong> sensors with readings</span>
    <span><strong>${quality.missing_sensors}</strong> sensors without readings</span>
    <span><strong>${coveragePercent(summary.co2)}%</strong> CO2 coverage over 24 hours</span>
  `;
}

function renderDisplayInsight(summary) {
  const insight = summary.insights[0];
  document.getElementById("display-insight").textContent = insight
    ? `${insight.title}. ${insight.body}`
    : "No meaningful campus pattern has been detected in the recent readings.";
}

function renderDisplayAction(summary) {
  const recommendation = summary.buildings.flatMap((building) => building.recommendations)[0];
  const audienceGrid = document.getElementById("display-action-audiences");
  if (!recommendation) {
    document.getElementById("display-action").textContent =
      "No recommendation is shown because current evidence is insufficient or conditions are not elevated.";
    document.getElementById("display-verify").textContent = "";
    audienceGrid.innerHTML = "";
    return;
  }

  document.getElementById("display-action").textContent =
    `${recommendation.title}. ${recommendation.interpretation}`;
  document.getElementById("display-verify").textContent = `Verify: ${recommendation.verification}`;
  const studentActions = recommendation.actions.filter((action) => /student/i.test(action));
  const facilitiesActions = recommendation.actions.filter((action) => /facilit/i.test(action));
  audienceGrid.innerHTML = `
    <article>
      <span>For students</span>
      <p>${escapeHtml(studentActions[0] || "Use another study area if the room feels crowded or uncomfortable.")}</p>
    </article>
    <article>
      <span>For facilities</span>
      <p>${escapeHtml(facilitiesActions[0] || "Review this pattern if it recurs during comparable periods.")}</p>
    </article>
  `;
}

async function renderDisplayChart(summary, methodology) {
  const selected = summary.buildings
    .filter((building) => building.co2.source_count > 0)
    .sort((a, b) => (b.co2.current ?? 0) - (a.co2.current ?? 0))[0];
  const history = selected ? await getHistory(selected.building.id, "1h") : { series: [] };
  const data = aggregateMetricHistory(history, "co2", { bucketMinutes: 5 });
  document.getElementById("scene-air-title").textContent = "Live CO2 readings · last hour";
  if (!data.length) {
    renderTimeSeriesChart({ container: "#display-co2-chart", data: [], metric: { label: "CO2" } });
    document.getElementById("display-chart-summary").textContent = selected
      ? "No CO2 measurements are available for the last hour."
      : "No CO2 sensor readings have been received yet.";
    return;
  }

  const latest = data[data.length - 1];
  const peak = data.reduce((best, point) => (point.value > best.value ? point : best), data[0]);

  renderTimeSeriesChart({
    container: "#display-co2-chart",
    data,
    metric: { label: `${selected.building.name} average CO2`, decimals: 0 },
    options: {
      fitContainer: true,
      margin: { top: 30, right: 24, bottom: 38, left: 84 },
      unit: "ppm",
      color: "#09298b",
      includeZero: false,
      smoothingWindow: 5,
      strokeWidth: 4,
      thresholds: methodology.co2_bands || [],
      annotations: [
        { type: "point", label: `Latest ${formatNumber(latest.value)} ppm`, time: latest.time, value: latest.value, dy: 34 },
        { type: "point", label: `Peak ${formatNumber(peak.value)} ppm`, time: peak.time, value: peak.value, dy: -22 },
        { type: "threshold", label: "Reference", value: methodology.co2_reference_ppm },
      ],
    },
  });

  const values = data.map((point) => point.value);
  document.getElementById("display-chart-summary").textContent =
    `${selected.building.name} CO2 ranged from ${formatNumber(Math.min(...values))} to ${formatNumber(Math.max(...values))} ppm in the last hour. The chart refreshes with the live display.`;
}

function startSceneRotation(config) {
  const scenes = Array.from(document.querySelectorAll(".display-scene"));
  const progress = document.getElementById("display-progress-fill");
  let index = 0;
  let started = Date.now();

  const setSceneVisibility = () => {
    scenes.forEach((scene, sceneIndex) => {
      scene.setAttribute("aria-hidden", String(sceneIndex !== index));
      scene.inert = sceneIndex !== index;
    });
  };
  setSceneVisibility();

  const show = (nextIndex) => {
    scenes[index].classList.remove("active");
    index = nextIndex % scenes.length;
    scenes[index].classList.add("active");
    scenes[index].scrollTop = 0;
    setSceneVisibility();
    started = Date.now();
  };

  setInterval(() => {
    if (document.getElementById("display-pulse").dataset.state !== "ready") {
      if (index !== 0) show(0);
      progress.style.width = "0";
      return;
    }
    const elapsed = Date.now() - started;
    progress.style.width = `${Math.min(100, (elapsed / config.sceneMs) * 100)}%`;
    if (elapsed >= config.sceneMs) {
      progress.style.width = "0";
      show(index + 1);
    }
  }, 250);
}

async function loadDisplayData(config) {
  const [summary, methodology] = await Promise.all([getCampusSummary(), getMethodology()]);
  renderDisplaySummary(summary);
  renderLocalFocus(summary, config);
  renderDisplayBuildings(summary);
  renderCampusMap(summary);
  renderDataQuality(summary);
  renderDisplayInsight(summary);
  renderDisplayAction(summary);
  await renderDisplayChart(summary, methodology);
  document.getElementById("display-pulse").dataset.state = "ready";
}

async function initDisplayPulse() {
  const config = displayConfig();
  document.getElementById("display-pulse").dataset.preset = config.presetName;
  document.getElementById("display-pulse").dataset.density = config.density;
  updateClock();
  updateDashboardUrl();
  setInterval(updateClock, 15_000);
  startSceneRotation(config);

  let status = null;
  try {
    status = await getSystemStatus();
    renderRuntimeStatus(status);
    updateDashboardUrl(status);
    await loadDisplayData(config);
  } catch (error) {
    renderDisplayUnavailable(error, status);
  }

  const refresh = async () => {
    try {
      status = await getSystemStatus();
      renderRuntimeStatus(status);
      updateDashboardUrl(status);
      await loadDisplayData(config);
    } catch (error) {
      renderDisplayUnavailable(error, status);
    }
    setTimeout(refresh, refreshIntervalMs(status));
  };
  setTimeout(refresh, refreshIntervalMs(status));
}
