import fs from 'node:fs/promises';
import { chromium } from 'playwright';

const base = new URL('https://tasi-ganzilla.vercel.app/');
const common = {
  gannzillaPro: 'true', forceUrlNumbers: 'true', levels: '10', divisions: '36', startValue: '3600', increment: '1', clockwise: 'true',
  uniformCellGeometry: 'true', uniformCellScale: '1.18', uniformCellBaseRingWidth: '82', uniformCellBaseInnerRadius: '245',
  centerCellOnlyAdjustment: 'true', centerCellScale: '1.12', gannzillaRingWidth: '96.75999999999999', gannzillaInnerRadius: '279.32000000000005',
  adaptiveCellGeometry: 'true', outerCyclesAfterAnchor: '10', secondRingNumbers: 'true', secondRingMode: 'digitalRoot', allCellsWhite: 'true',
  paintPreview: 'true', paintStageSize: '1280', paintZoomAuthority: 'true', paintZoomPercent: '125',
  centerLogo: 'true', centerLogoClockToggle: 'true', centerClockUnifiedGeometry: 'true', centerClockUnifiedScale: '1.18',
  emptyOuterRing: 'true', emptyOuterRingCount: '5', zodiacOuterRing: 'true', weekdaysOuterRing: 'true', angleOuterRing: 'true',
  singleVisibleWheelAuthority: 'true', liveCanvasDisplay: 'true', resetVerticalPan: 'true', v: '657', cacheBust: String(Date.now()),
};

const viewports = [{ width: 1008, height: 650 }, { width: 1365, height: 768 }];
const browser = await chromium.launch({ headless: true });
const results = [];

for (const viewport of viewports) {
  const page = await browser.newPage({ viewport });
  const url = new URL(base);
  for (const [key, value] of Object.entries(common)) url.searchParams.set(key, value);
  await page.goto(url.href, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(5000);
  const logo = page.locator('#gannzilla-center-logo-responsive-81-v596');
  if (await logo.count()) await logo.click({ force: true });
  await page.waitForTimeout(3000);

  const data = await page.evaluate(() => {
    const ids = {
      display: 'gannzilla-center-clock-display-v614',
      date: 'gannzilla-center-clock-date-v614',
      upperAngle: 'gannzilla-center-clock-angle-row-v614',
      upperTime: 'gannzilla-center-clock-time-row-v614',
      divider: 'gannzilla-center-clock-divider-v614',
      lowerTime: 'gannzilla-center-clock-lower-time-row-v624',
      lowerAngle: 'gannzilla-center-clock-lower-angle-row-v624',
      hijri: 'gannzilla-center-clock-lower-hijri-date-v624',
    };
    const rect = (id) => {
      const el = document.getElementById(id);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return { id, top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height, fontSize: s.fontSize, cssTop: s.top, text: el.textContent?.trim() || '' };
    };
    const out = Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, rect(id)]));
    if (out.display && out.upperTime && out.divider && out.lowerTime && out.date && out.hijri) {
      out.metrics = {
        gapBetweenTimesPx: out.lowerTime.top - out.upperTime.bottom,
        upperDividerClearancePx: out.divider.top - out.upperTime.bottom,
        lowerDividerClearancePx: out.lowerTime.top - out.divider.bottom,
        dividerTopPercent: ((out.divider.top + out.divider.height / 2 - out.display.top) / out.display.height) * 100,
        dateFrameClearancePx: out.date.top - out.display.top,
        hijriFrameClearancePx: out.display.bottom - out.hijri.bottom,
        pass: (out.divider.top - out.upperTime.bottom) >= 6
          && (out.lowerTime.top - out.divider.bottom) >= 6
          && (out.date.top - out.display.top) >= 20
          && (out.display.bottom - out.hijri.bottom) >= 20,
      };
    }
    return out;
  });

  results.push({ variant: 'unified-v657', viewport, url: url.href, ...data });
  await page.close();
}

await browser.close();
await fs.mkdir('diagnostics/clock-geometry', { recursive: true });
await fs.writeFile('diagnostics/clock-geometry/result.json', JSON.stringify(results, null, 2));
console.log('CLOCK_GEOMETRY_V657_RESULT=' + JSON.stringify(results));
