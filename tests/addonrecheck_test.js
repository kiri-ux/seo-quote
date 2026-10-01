// THE RECHECK READS THE ADD-ON COUNT AGAIN.
//
// Valero's run lost 32 of 40 rank lookups and the hidden-market probes with
// them, so the add-on count saw two of five markets and recommended none. The
// automatic recheck filled the ranks in and repriced on that same zero. It now
// retries the probes and asks for the count again. (2026-10-01, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 140)));
  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };
  const json = (route, o) => route.fulfill({status: 200,
    contentType: 'application/json', body: JSON.stringify(o)});
  const HIDDEN = /palm springs|reno|salinas/;
  let probesUp = false;
  const addonBodies = [], priceBodies = [];
  await p.route('**/api/rankings', route => {
    const kws = ((route.request().postDataJSON() || {}).batch || []).map(x => x.kw);
    return json(route, {results: kws.map(kw => (HIDDEN.test(kw) && !probesUp)
      ? {kw, pos: '—', error: true}
      : {kw, pos: null, ranked_top: false, error: false})});
  });
  await p.route('**/api/addon_suggestion', route => {
    const body = route.request().postDataJSON();
    addonBodies.push(body);
    const hidden = (body.table || []).filter(x => HIDDEN.test(x.kw)).length;
    return json(route, {suggested: hidden ? 4 : 0, basis: hidden ? 'five' : 'two'});
  });
  await p.route('**/api/price', route => {
    priceBodies.push(route.request().postDataJSON());
    return json(route, {handoff: {package: {base: 2900, intermediate: 3900,
      advanced: 4900}}, total_volume: 10250, pct_not_ranking: 100});
  });
  await p.route('**/api/metrics', route => json(route, {adder: 0}));
  await p.route('**/api/market_signals', route => json(route, {}));
  await p.route('**/api/serp_**', route => json(route, {}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout: 15000});

  await p.evaluate(async () => {
    ROW = 0;
    const r = ROWS[0];
    r.kind = 'seo';
    r.band = 'non_contiguous_region';
    r.kw = {all: [{kw: 'injury lawyer seattle wa', vol: 100},
                  {kw: 'injury lawyer las vegas nv', vol: 100}],
            off_grid_probes: ['injury lawyer palm springs ca', 'injury lawyer reno nv',
                              'injury lawyer salinas ca'].map(kw => ({kw, market: kw}))};
    r.kw.head = r.kw.all.slice();
    r.data = Object.assign({}, r.data, {g_city: 1, brand: 'Valero', site: 'valero.com',
      city: ['Palm Springs, CA', 'Reno, NV', 'Salinas, CA', 'Seattle, WA', 'Las Vegas, NV']});
    load(formOf(r), r.data);
    await generate();
  });
  say('the build priced on no add-ons while the probes failed',
      (priceBodies[0] || {}).addon_markets === 0, priceBodies[0]);

  probesUp = true;
  const n0 = priceBodies.length;
  await p.evaluate(async () => {
    const r = ROWS[0];
    // A term still unmeasured, so the recheck has table work too.
    r.result.ranks['injury lawyer seattle wa'] = '—';
    r.openRun = 0;
    await recheckRanks(0);
  });
  const last = addonBodies[addonBodies.length - 1] || {};
  say('the recheck asks for the add-on count again',
      addonBodies.length >= 2, addonBodies.length);
  say('with the hidden markets measured',
      (last.table || []).filter(x => /palm springs|reno|salinas/.test(x.kw)).length === 3,
      last.table);
  const rp = priceBodies.slice(n0).pop() || {};
  say('and reprices on the new count', rp.addon_markets === 4, rp);
  const res = await p.evaluate(() => ROWS[0].result.addon);
  say('the run records it', (res || {}).suggested === 4, res);
  say('no page errors', errs.length === 0, errs);
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
