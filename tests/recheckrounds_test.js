// RANKS RECHECK UNTIL DONE, NOT ONCE.
//
// Terms still failing after the automatic recheck waited for someone to press
// Check ranks again. The run now retries by itself, up to three more rounds.
// (2026-10-01, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 160)));
  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };
  const json = (route, o) => route.fulfill({status: 200,
    contentType: 'application/json', body: JSON.stringify(o)});
  // Every lookup fails for the first three requests, then everything answers.
  let calls = 0;
  await p.route('**/api/rankings', route => {
    calls++;
    const kws = ((route.request().postDataJSON() || {}).batch || []).map(x => x.kw);
    const ok = calls > 3;
    return json(route, {results: kws.map(kw => ok
      ? {kw, pos: 7, ranked_top: true, error: false}
      : {kw, pos: '—', error: true})});
  });
  await p.route('**/api/price', route => json(route, {handoff: {package: {base: 2900,
    intermediate: 3900, advanced: 4900}}}));
  await p.route('**/api/metrics', route => json(route, {adder: 0}));
  await p.route('**/api/market_signals', route => json(route, {}));
  await p.route('**/api/serp_**', route => json(route, {}));
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout: 15000});

  await p.evaluate(async () => {
    RECHECK_WAIT_MS = 50;
    ROW = 0;
    const r = ROWS[0];
    r.kind = 'seo';
    r.kw = {all: [{kw: 'drain cleaning boca raton', vol: 100},
                  {kw: 'sewer repair boca raton', vol: 90}]};
    r.kw.head = r.kw.all.slice();
    r.data = Object.assign({}, r.data, {g_city: 1, city: ['Boca Raton, FL'],
                                        brand: 'Drainify', site: 'drainify.com'});
    load(formOf(r), r.data);
    await generate();
  });
  // Wait for the background rounds.
  for (let i = 0; i < 50; i++) {
    const left = await p.evaluate(() => Object.values(ROWS[0].result.ranks || {})
      .filter(v => v === '—').length);
    if (!left) break;
    await p.waitForTimeout(200);
  }
  const ranks = await p.evaluate(() => ROWS[0].result.ranks);
  say('every term ends up measured without a click',
      Object.values(ranks).every(v => v === 7), ranks);
  say('it took more than one recheck', calls >= 4, calls);
  say('no page errors', errs.length === 0, errs);
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
