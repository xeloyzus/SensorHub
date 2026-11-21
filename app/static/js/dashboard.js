const PULSE_REFRESH_MS = 60_000;

function formatNumber(value, decimals = 0) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString([], {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  });
}

function formatMetric(metric, decimals = 0) {
  const value = metric?.current ?? metric?.last_known;
  if (value == null) return "--";
  return `${formatNumber(value, decimals)} ${metric.unit}`;
}

function metricAgeText(minutes) {
  if (minutes == null) return "age unknown";
  if (minutes < 60) return `${minutes} min old`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  const days = Math.floor(hours / 24);
  return days
    ? `${days}d ${hours % 24}h ${remainingMinutes}m old`
    : `${hours}h ${remainingMinutes}m old`;
}

function metricContext(metric) {
  if (metric?.current == null && metric?.last_known != null) {
    const count = metric.last_known_source_count || 0;
    const sourceText = `${count} sensor${count === 1 ? "" : "s"}`;
    return `Last known · ${sourceText} · oldest value ${metricAgeText(metric.last_known_age_minutes)} · not current`;
  }
  if (!metric || metric.sample_count === 0) return "No 24-hour history yet";
  const direction =
    metric.change_1h == null
      ? "No one-hour trend yet"
      : `${metric.change_1h >= 0 ? "+" : ""}${formatNumber(metric.change_1h, metric.unit === "°C" ? 1 : 0)} ${metric.unit} in 1 h`;
  return `${direction} · ${formatNumber(metric.coverage_24h * 100)}% coverage`;
}

function setCard(id, value, context) {
  const card = document.getElementById(id);
  card.querySelector(".metric-card-value").textContent = value;
  card.querySelector(".metric-card-context").textContent = context;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function refreshIntervalMs(status) {
  const seconds = Number(status && status.display_refresh_seconds);
  return Number.isFinite(seconds) && seconds >= 10 ? seconds * 1000 : PULSE_REFRESH_MS;
}

function renderDataSource(status) {
  const badge = document.getElementById("data-source-badge");
  if (!badge || !status) return;
  badge.textContent = "Sensor readings";
  badge.className = "freshness-badge current";
}

function freshnessLabel(freshness) {
  if (!freshness) return "Freshness unknown";
  if (freshness.status === "current") return "Current";
  if (freshness.status === "delayed") return "Delayed";
  if (freshness.status === "stale") return "Stale";
  return "Unknown";
}

function renderBuildings(buildings) {
  const grid = document.getElementById("building-grid");
  grid.innerHTML = buildings
    .map((summary) => {
      const recommendation = summary.recommendations[0];
      return `
        <article class="building-pulse-card">
          <div class="building-card-head">
            <h3>${escapeHtml(summary.building.name)}</h3>
            <span class="freshness-badge ${summary.data_quality.freshness.status}">
              ${freshnessLabel(summary.data_quality.freshness)}
            </span>
          </div>
          <div class="building-metrics">
            <span><em>CO2</em><strong>${formatMetric(summary.co2)}</strong></span>
            <span><em>Temperature</em><strong>${formatMetric(summary.temperature, 1)}</strong></span>
            <span><em>Electricity</em><strong>${summary.energy.current_kw == null ? "--" : `${formatNumber(summary.energy.current_kw, 1)} kW`}</strong></span>
          </div>
          <p>${escapeHtml(metricContext(summary.co2))}</p>
          ${
            recommendation
              ? `<div class="mini-recommendation">Possible action · ${escapeHtml(recommendation.verification)}</div>`
              : `<div class="mini-recommendation quiet">No action suggested right now.</div>`
          }
        </article>
      `;
    })
    .join("");
}

function renderInsights(summary) {
  const feed = document.getElementById("insight-feed");
  const insights = summary.insights.length
    ? summary.insights
    : [{ title: "No notable pattern yet", body: "The dashboard did not detect a meaningful change in the recent readings.", severity: "info" }];
  feed.innerHTML = insights
    .map(
      (insight) => `
        <article class="insight-card ${insight.severity}">
          <span>${escapeHtml(insight.severity)}</span>
          <h3>${escapeHtml(insight.title)}</h3>
          <p>${escapeHtml(insight.body)}</p>
        </article>
      `
    )
    .join("");
}

function renderRecommendations(summary) {
  const feed = document.getElementById("recommendation-feed");
  const recommendations = summary.buildings.flatMap((building) => building.recommendations);
  if (!recommendations.length) {
    feed.innerHTML = `
      <article class="insight-card">
        <span>Monitoring</span>
        <h3>No action suggested right now</h3>
        <p>Suggestions appear when enough recent readings show a sustained change.</p>
      </article>
    `;
    return;
  }

  feed.innerHTML = recommendations
    .map(
      (item) => `
        <article class="recommendation-card">
          <span>${escapeHtml(item.confidence)} confidence · ${escapeHtml(item.audience.join(", "))}</span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.interpretation)}</p>
          <ul>${item.actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ul>
          <strong>Verify:</strong>
          <p>${escapeHtml(item.verification)}</p>
        </article>
      `
    )
    .join("");
}

async function renderCampusChart(summary, methodology) {
  const bestBuilding = summary.buildings
    .filter((building) => building.co2.source_count > 0 || building.co2.last_known_source_count > 0)
    .sort((a, b) => (b.co2.current ?? b.co2.last_known ?? 0) - (a.co2.current ?? a.co2.last_known ?? 0))[0];
  const history = bestBuilding ? await getHistory(bestBuilding.building.id, "1h") : { series: [] };
  const data = aggregateMetricHistory(history, "co2", { bucketMinutes: 5 });
  document.getElementById("timeline-title").textContent = "Live CO2 readings · last hour";
  if (!data.length) {
    renderTimeSeriesChart({ container: "#co2-chart", data: [], metric: { label: "CO2" } });
    document.getElementById("timeline-summary").textContent = bestBuilding
      ? "No CO2 readings arrived in the last hour. Last known sensor values above are labeled with their age."
      : "No CO2 sensor readings have been received yet.";
    return;
  }

  renderTimeSeriesChart({
    container: "#co2-chart",
    data,
    metric: { label: `${bestBuilding.building.name} average CO2`, decimals: 0 },
    options: {
      unit: "ppm",
      color: "#09298b",
      includeZero: false,
      smoothingWindow: 3,
      thresholds: methodology.co2_bands || [],
    },
  });

  const values = data.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  document.getElementById("timeline-summary").textContent =
    `${bestBuilding.building.name} CO2 ranged from ${formatNumber(min)} to ${formatNumber(max)} ppm in the last hour. The chart refreshes with the live dashboard.`;
}

async function initCampusPulse() {
  let status = null;
  const render = async () => {
    try {
      [status] = await Promise.all([getSystemStatus()]);
      renderDataSource(status);
      const [summary, methodology] = await Promise.all([getCampusSummary(), getMethodology()]);
      document.getElementById("campus-status").textContent = summary.co2.current != null
        ? `Average campus CO2 is ${formatNumber(summary.co2.current)} ppm across ${summary.co2.source_count} reporting air sensors.`
        : summary.co2.last_known != null
          ? `Current data is unavailable. Last known campus CO2 was ${formatNumber(summary.co2.last_known)} ppm across ${summary.co2.last_known_source_count} sensors (${metricAgeText(summary.co2.last_known_age_minutes)}).`
          : "No CO2 sensor readings have been received yet.";
      const badge = document.getElementById("freshness-badge");
      badge.textContent = freshnessLabel(summary.data_quality.freshness);
      badge.className = `freshness-badge ${summary.data_quality.freshness.status}`;
      document.getElementById("latest-reading").textContent = summary.data_quality.freshness.description;

      setCard("air-card", formatMetric(summary.co2), metricContext(summary.co2));
      setCard("temperature-card", formatMetric(summary.temperature, 1), metricContext(summary.temperature));
      setCard(
        "energy-card",
        summary.energy.current_kw == null ? "--" : `${formatNumber(summary.energy.current_kw, 1)} kW`,
        summary.energy.method
      );

      renderBuildings(summary.buildings);
      renderInsights(summary);
      renderRecommendations(summary);
      await renderCampusChart(summary, methodology);
      document.getElementById("overview-error").hidden = true;
    } catch (error) {
      const banner = document.getElementById("overview-error");
      banner.textContent = "The sensor connection is unavailable. Any values shown may be out of date. Reconnecting automatically.";
      banner.hidden = false;
      const badge = document.getElementById("freshness-badge");
      badge.textContent = "Connection unavailable";
      badge.className = "freshness-badge stale";
    }
  };

  await render();
  const refresh = async () => {
    await render();
    setTimeout(refresh, refreshIntervalMs(status));
  };
  setTimeout(refresh, refreshIntervalMs(status));
}
