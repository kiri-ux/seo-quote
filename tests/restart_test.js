// A RESTART IS NOT A FAILED REQUEST. The host answers 502 for the half-minute
// it takes to come back, and every button pressed in that window reported a
// dead end -- as a doctype pasted into a panel heading.
const {chromium} = require('/root/work/node_modules/playwright-core');
const HTML502 = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">'
  + '<meta name="viewport" content="width=device-width, initial-scale=1">'
  + '<title>502 Bad Gateway</title></head><body>502</body></html>';

(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  // The first two rank calls hit a restarting instance; the third succeeds.
  let rankCalls = 0, priceCalls = 0;
  await p.route('**/api/rankings', route => {
    rankCalls++;
    if (rankCalls <= 2)
      return route.fulfill({status:502, contentType:'text/html', body: HTML502});
    const body = route.request().postDataJSON() || {};
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({results: (body.batch || []).map((x, i) => ({
        kw: x.kw, pos: i === 0 ? 5 : 'Not Found', ranked_top: i === 0, error: false}))})});
  });
  await p.route('**/api/price', route => {
    priceCalls++;
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({handoff:{package:{base:2900,intermediate:3900,advanced:4900}},
                            total_volume: 4690, pct_not_ranking: 50})});
  });
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
  await p.evaluate(() => {
    const r = ROWS[0];
    r.result.ranks = {};
    r.result.table = ((r.kw || {}).all || []).map(x => ({
      kw: x.kw, pos: '—', ranked_top: false, error: true}));
    r.result.table.forEach(x => { r.result.ranks[x.kw.toLowerCase()] = '—'; });
    r.data.g_city = 1; r.data.city = ['Boca Raton, FL'];
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(300);

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  await p.click(hist + ' [data-recheck]');
  // The backoff is 0 / 4s / 10s / 20s, so the third attempt lands ~14s in.
  for (let i = 0; i < 60 && rankCalls < 3; i++) await p.waitForTimeout(1000);
  await p.waitForTimeout(2000);

  say('rodeOutTheRestart', rankCalls >= 3, rankCalls + ' calls to /api/rankings');
  say('repricedAfterwards', priceCalls >= 1, priceCalls + ' calls to /api/price');
  const ranks = await p.evaluate(() => Object.values(ROWS[0].result.ranks));
  say('ranksLanded', !ranks.every(v => v === '—'), JSON.stringify(ranks.slice(0,3)));

  const msg = await p.textContent(hist + ' [data-rkmsg]');
  say('noDoctypeOnScreen', !/DOCTYPE|<html|viewport/i.test(msg), msg);

  // A 502 that never clears is reported as a restart, in one sentence.
  await p.unroute('**/api/rankings');
  await p.route('**/api/rankings', route =>
    route.fulfill({status:502, contentType:'text/html', body: HTML502}));
  await p.evaluate(() => {
    const r = ROWS[0];
    Object.keys(r.result.ranks).forEach(k => { r.result.ranks[k] = '—'; });
    r.result.table.forEach(x => { x.pos = '—'; x.error = true; });
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  if (!(await p.$(hist + ' [data-recheck]')))
    await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForSelector(hist + ' [data-recheck]', {timeout: 10000});
  await p.click(hist + ' [data-recheck]');
  // All four attempts fail: 0 + 4 + 10 + 20 = 34s of waiting before it gives up.
  for (let i = 0; i < 90; i++) {
    const t = await p.textContent(hist + ' [data-rkmsg]').catch(() => '');
    if (/did not answer/.test(t)) break;
    await p.waitForTimeout(1000);
  }
  const m2 = await p.textContent(hist + ' [data-rkmsg]');
  say('givesUpInASentence', /did not answer \(502\)/.test(m2), m2);
  say('stillNoDoctype', !/DOCTYPE|<html/i.test(m2), m2);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
