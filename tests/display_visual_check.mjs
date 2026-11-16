/**
 * Optional live responsive check (requires Playwright).
 * Start the app with an isolated test database, then run:
 *   node tests/display_visual_check.mjs http://127.0.0.1:8000/
 * Each page stays open while its viewport rotates, exercising chart resizing.
 */
const targetUrl = process.argv[2] || "http://127.0.0.1:8000/";
let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  console.error("Playwright is not installed. Install it to run responsive visual checks.");
  process.exit(2);
}

const sizes = [
  [1920, 1080], [1366, 768], [1280, 720], [3840, 2160],
  [1080, 1920], [768, 1024], [320, 568], [390, 844], [844, 390],
];
const browser = await chromium.launch();
const issues = [];
try {
  const page = await browser.newPage({ reducedMotion: "reduce" });
  for (const path of ["/", "/overview", "/mobile"]) {
    const url = new URL(path, targetUrl);
    url.searchParams.set("scene_ms", "3600000");
    await page.goto(url.href, { waitUntil: "networkidle" });
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      // Let ResizeObserver and its subsequent layout complete after rotation.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const failures = await page.evaluate(() => {
        const failures = [];
        if (document.documentElement.scrollWidth > innerWidth + 2) failures.push("Page has horizontal overflow");
        if (new RegExp("nanites" + "lab|uis campus pulse|demo data", "i").test(document.documentElement.outerHTML)) failures.push("Old branding is present");
        const scenes = [...document.querySelectorAll(".display-scene")];
        const containers = scenes.length ? scenes : [...document.querySelectorAll("main, body > header")];
        for (const container of containers) {
          const bounds = container.getBoundingClientRect();
          const scrollable = getComputedStyle(container).overflowY === "auto";
          const offenders = [...container.querySelectorAll("*")].filter(el => {
            if (el.closest("svg") || el.classList.contains("display-map-bar")) return false;
            const box = el.getBoundingClientRect();
            if (!box.width || !box.height || getComputedStyle(el).display === "none") return false;
            const left = scenes.length ? bounds.left : 0;
            const right = scenes.length ? bounds.right : innerWidth;
            return box.left < left - 3 || box.right > right + 3 ||
              (scenes.length && !scrollable && (box.bottom > bounds.bottom + 3 || box.top < bounds.top - 3));
          });
          if (offenders.length) failures.push({
            scene: container.dataset.scene || container.tagName,
            elements: offenders.slice(0, 5).map(el => el.className || el.tagName),
          });
        }
        const chart = document.querySelector(".display-chart");
        const svg = chart?.querySelector("svg");
        if (svg) {
          const style = getComputedStyle(chart);
          const expectedWidth = chart.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
          if (Math.abs(svg.viewBox.baseVal.width - expectedWidth) > 2) failures.push("Chart did not resize after rotation");
        }
        return failures;
      });
      if (failures.length) issues.push({ path, width, height, failures });
    }
  }
} finally {
  await browser.close();
}
if (issues.length) {
  console.error(JSON.stringify(issues, null, 2));
  process.exit(1);
}
console.log(`Responsive checks passed for 3 pages at ${sizes.length} sizes, including rotation.`);
