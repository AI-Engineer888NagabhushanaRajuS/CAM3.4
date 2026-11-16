const { createRequire } = require('module');
const path = require('path');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  await p.getByRole('button', { name: /Sign in as Tester/i }).click();
  await p.waitForTimeout(6000);
  await p.evaluate(() => sessionStorage.clear());
  await p.reload({ waitUntil: 'networkidle' });
  await p.waitForTimeout(4000);
  console.log('buttons:', JSON.stringify(await p.evaluate(() => [...document.querySelectorAll('button')].map((x) => x.textContent.trim()).filter(Boolean).slice(0, 8))));
  await p.screenshot({ path: path.join(__dirname, 'screenshots', 'after-reload.png') });
  await b.close();
})();
