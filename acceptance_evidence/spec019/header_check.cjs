const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  for (const [w, h] of [[1280, 800], [1024, 768], [390, 844]]) {
    const p = await (await b.newContext({ viewport: { width: w, height: h } })).newPage();
    await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
    const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
    await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 15000 });
    await p.waitForTimeout(1200);
    const m = await p.evaluate(() => {
      const g = document.querySelector('[role=radiogroup][aria-label="Model provider"]');
      const header = g.closest('div.border-b');
      const h2 = header.querySelector('h2');
      const r = (e) => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.width)]; };
      return { header: r(header), title: r(h2), titleText: h2.textContent, titleClipped: h2.scrollWidth > h2.clientWidth, group: r(g), docOverflowX: document.documentElement.scrollWidth > window.innerWidth };
    });
    console.log(w + 'px', JSON.stringify(m));
    await p.screenshot({ path: `${OUT}/17-header-${w}.png` });
    await p.context().close();
  }
  await b.close();
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
