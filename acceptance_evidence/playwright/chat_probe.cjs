// One real question through the daemon's assistant with the OpenRouter switch on. Prints the reply's model and message (never a key).
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForTimeout(3000);
  const out = await p.evaluate(async () => {
    const sess = JSON.parse(sessionStorage.getItem('accomplish_session') || 'null');
    const r = await fetch('http://localhost:9334/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json', ...(sess?.token ? { Authorization: 'Bearer ' + sess.token } : {}) },
      body: JSON.stringify({ messages: [{ role: 'user', content: 'Say hello in five words.' }], scope: { mode: 'all' }, fileRefs: [], provider: 'openrouter' }) });
    return { status: r.status, body: (await r.text()).slice(0, 500) };
  });
  console.log(JSON.stringify(out));
  await b.close();
})();
