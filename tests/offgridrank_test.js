// MARKETS THE TABLE LEAVES OUT ARE STILL RANK-CHECKED.
//
// Valero named five markets; the grid crossed two. The add-on count reads the
// rank check, so three markets with no rows were never measured and the count
// came back "only 2 of 5 measured", suggesting nothing. The build now carries
// probe terms for those markets; step 3 checks them and hands them to the
// add-on count only -- not the proposal table, not the not-ranking share.
// (2026-10-01, Kiri)
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

  const rankBatches = [];
  let addonBody = null, priceBody = null;
  await p.route('**/api/rankings', route => {
    const kws = ((route.request().postDataJSON() || {}).batch || []).map(x => x.kw);
    rankBatches.push(kws);
    return json(route, {results: kws.map(kw => ({kw, pos: /reno|salinas|palm/.test(kw)
      ? 4 : '—', ranked_top: /reno|salinas|palm/.test(kw), error: false}))});
  });
  await p.route('**/api/addon_suggestion', route => {
    addonBody = route.request().postDataJSON();
    return json(route, {suggested: 0, basis: ''});
  });
  await p.route('**/api/price', route => {
    priceBody = route.request().postDataJSON();
    return json(route, {handoff: {package: {base: 2900, intermediate: 3900,
      advanced: 4900}}, total_volume: 4690, pct_not_ranking: 100});
  });
  await p.route('**/api/metrics', route => json(route, {adder: 0}));
  await p.route('**/api/market_signals', route => json(route, {}));
  await p.route('**/api/serp_**', route => json(route, {}));
  await p.route('**/api/geo_scope**', route => json(route, {band: 'non_contiguous_region'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout: 15000});

  const PROBES = ['injury lawyer palm springs ca', 'injury lawyer reno nv',
                  'injury lawyer salinas ca'];
  const out = await p.evaluate(async probes => {
    ROW = 0;
    const r = ROWS[0];
    r.kind = 'seo';
    r.band = 'non_contiguous_region';
    r.kw = {all: [{kw: 'injury lawyer seattle', vol: 100},
                  {kw: 'injury lawyer las vegas nv', vol: 100}],
            off_grid_probes: probes.map(kw => ({kw, market: kw}))};
    r.kw.head = r.kw.all.slice();
    r.data = Object.assign({}, r.data, {g_city: 1, brand: 'Valero', site: 'valero.com',
      city: ['Palm Springs, CA', 'Reno, NV', 'Salinas, CA', 'Seattle, WA', 'Las Vegas, NV']});
    load(formOf(r), r.data);
    await generate();
    const res = r.result || {};
    return {table: (res.table || []).map(x => x.kw),
            offGrid: (res.offGrid || []).map(x => x.kw)};
  }, PROBES);

  const sent = rankBatches.flat();
  say('every hidden market is rank-checked',
      PROBES.every(k => sent.includes(k)), sent);
  say('the probes stay out of the proposal table',
      !out.table.some(k => PROBES.includes(k)), out.table);
  say('the add-on count sees them',
      PROBES.every(k => ((addonBody || {}).table || []).some(x => x.kw === k)),
      addonBody);
  say('the not-ranking share is the table\'s own',
      (priceBody || {}).pct_not_ranking === 100, priceBody);
  say('the run keeps the probe rows', out.offGrid.length === 3, out.offGrid);
  say('no page errors', errs.length === 0, errs);
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
