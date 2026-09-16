// RECHECK RANKS ON A QUOTE REOPENED FROM STORAGE. rankReq is not in the saved
// payload, so every reloaded quote returned without checking anything -- which
// is what "tried recheck ranks and got nothing" was.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  const rankCalls = [], priceCalls = [];
  await p.route('**/api/rankings', route => {
    const body = route.request().postDataJSON() || {};
    rankCalls.push(body);
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({results: (body.batch || []).map((x, n) => ({
        kw: x.kw, pos: n === 0 ? 4 : 'Not Found',
        ranked_top: n === 0, error: false}))})});
  });
  await p.route('**/api/price', route => {
    priceCalls.push(route.request().postDataJSON() || {});
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({handoff: {package: {base: 2900, intermediate: 3900,
                                                advanced: 4900}},
                            total_volume: 4690, pct_not_ranking: 50,
                            min_term_months: 6})});
  });
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body: '{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast', {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});

  // A quote as it comes back from storage: no rankReq, no priceReq, and every
  // rank check failed.
  await p.evaluate(() => {
    const r = ROWS[0];
    delete r.result.rankReq;
    delete r.result.priceReq;
    r.result.ranks = {};
    r.result.table = ((r.kw || {}).all || []).map(x => ({
      kw: x.kw, pos: '—', ranked_top: false, error: true}));
    r.result.table.forEach(x => { r.result.ranks[x.kw.toLowerCase()] = '—'; });
    r.data.g_city = 1;
    r.data.city = ['Boca Raton, FL'];
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(300);

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  say('buttonThere', (await p.$$eval(`${hist} [data-recheck]`, n => n.length)) === 1);
  await p.click(`${hist} [data-recheck]`);
  await p.waitForTimeout(1500);

  say('askedForRanks', rankCalls.length > 0, 'no /api/rankings call was made');
  const first = rankCalls[0] || {};
  say('carriedMarkets', (first.geo_values || []).includes('Boca Raton, FL'),
      JSON.stringify(first.geo_values));
  say('carriedDomain', !!first.domain, JSON.stringify(Object.keys(first)));
  say('onlyFailedTerms', (first.batch || []).length > 0,
      JSON.stringify((first.batch || []).length));
  say('repriced', priceCalls.length > 0, 'no /api/price call was made');
  const pr = priceCalls[priceCalls.length - 1] || {};
  say('priceHasPct', typeof pr.pct_not_ranking === 'number', JSON.stringify(pr.pct_not_ranking));
  say('priceHasBand', !!pr.band, JSON.stringify(pr.band));
  say('priceHasMarkup', typeof pr.markup_pct === 'number', JSON.stringify(pr.markup_pct));

  // The ranks on screen moved.
  const ranks = await p.evaluate(() => Object.values(ROWS[0].result.ranks));
  say('ranksUpdated', !ranks.every(v => v === '—'), JSON.stringify(ranks.slice(0, 4)));

  // A quote with every rank already known says so instead of going quiet.
  await p.evaluate(() => {
    const r = ROWS[0];
    Object.keys(r.result.ranks).forEach(k => { r.result.ranks[k] = 3; });
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  // The run may already be open from the first pass; only open it if it is not.
  if (!(await p.$('.prod[data-row="0"] [data-pane="history"] [data-recheck]')))
    await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForSelector('.prod[data-row="0"] [data-pane="history"] [data-recheck]',
                          {timeout: 10000});
  const before = rankCalls.length;
  await p.click(`${hist} [data-recheck]`);
  await p.waitForTimeout(500);
  say('nothingToDo.noCall', rankCalls.length === before, 'it checked anyway');
  say('nothingToDo.saysSo',
      /already has a rank/.test(await p.textContent(`${hist} [data-rkmsg]`)),
      await p.textContent(`${hist} [data-rkmsg]`));

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
