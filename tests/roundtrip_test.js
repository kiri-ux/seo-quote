// A RECHECK HAS TO SURVIVE A RELOAD. The ranks moved on screen and the quote
// repriced, then the page came back showing the figures it was saved with.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  // A store that behaves like the real one: PUT replaces the saved payload.
  let stored = null;
  const puts = [];
  await p.route('**/api/quotes**', route => {
    const rq = route.request();
    if (rq.method() === 'POST') {
      stored = rq.postDataJSON();
      return route.fulfill({status:200, contentType:'application/json',
                            body: JSON.stringify({id: 9})});
    }
    if (rq.method() === 'PUT') {
      stored = rq.postDataJSON();
      puts.push(stored);
      return route.fulfill({status:200, contentType:'application/json', body:'{}'});
    }
    if (rq.url().includes('/api/quotes/9'))
      return route.fulfill({status:200, contentType:'application/json',
        body: JSON.stringify(Object.assign({id: 9, client: 'Drainify', tool: 'seo'},
                                           stored || {}))});
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({enabled: true, quotes: stored
        ? [{id: 9, client: 'Drainify', tool: 'seo', name: stored.name,
            updated_at: '2026-09-16', payload: stored.payload}] : []})});
  });
  await p.route('**/api/quotes/status**', route =>
    route.fulfill({status:200, contentType:'application/json',
                   body: JSON.stringify({enabled:true, detail:''})}));

  await p.route('**/api/rankings', route => {
    const body = route.request().postDataJSON() || {};
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({results: (body.batch || []).map(x => ({
        kw: x.kw, pos: 7, ranked_top: true, error: false}))})});
  });
  await p.route('**/api/price', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({handoff:{package:{base:1111,intermediate:2222,advanced:3333}},
                            total_volume: 4690, pct_not_ranking: 0, min_term_months: 6})}));
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  const openRun = async () => {
    await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
    await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
    if (!(await p.$(hist + ' [data-recheck]')))
      await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
    await p.waitForSelector(hist + ' [data-recheck]', {timeout:10000});
  };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  // A quote as storage hands it back: a history entry whose quote is its OWN
  // object, every rank failed, and an old single-price response line.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.saveId = 9;
    r.data.brand = 'Drainify';
    r.result.ranks = {};
    r.result.table = ((r.kw || {}).all || []).map(x => ({
      kw: x.kw, pos: '—', ranked_top: false, error: true}));
    r.result.table.forEach(x => { r.result.ranks[x.kw.toLowerCase()] = '—'; });
    r.result.pricing = Object.assign({}, r.result.pricing,
      {pct_not_ranking: null, total_volume: 4690});
    r.history = [{when: '9/16/2026, 8:37:29 AM', resp: '$5,350/mo · 21 terms',
                  quote: JSON.parse(JSON.stringify(r.result))}];
    r.data.g_city = 1; r.data.city = ['Boca Raton, FL'];
    draw();
  });
  await openRun();
  await p.click(hist + ' [data-recheck]');
  for (let i = 0; i < 40 && !puts.length; i++) await p.waitForTimeout(500);
  await p.waitForTimeout(1500);

  say('itSaved', puts.length > 0, 'no PUT reached the store');
  const pay = ((puts[puts.length - 1] || {}).payload || {}).adtini || {};
  const savedRanks = Object.values((pay.result || {}).ranks || {});
  say('savedRanksMoved', savedRanks.length && savedRanks.every(v => v === 7),
      JSON.stringify(savedRanks.slice(0, 3)));
  say('savedPriceMoved', ((pay.result || {}).pricing || {}).pct_not_ranking === 0,
      JSON.stringify(((pay.result || {}).pricing || {}).pct_not_ranking));
  const h0 = (pay.history || [])[0] || {};
  say('savedRunRanksMoved',
      Object.values((h0.quote || {}).ranks || {}).every(v => v === 7),
      JSON.stringify(Object.values((h0.quote || {}).ranks || {}).slice(0, 3)));
  say('savedRunRespMoved', /1,111 \/ \$2,222 \/ \$3,333/.test(String(h0.resp)), h0.resp);

  // NOW RELOAD, with the client list naming the record the PUT went to.
  await p.route('**/api/adtini/clients**', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({enabled: true, clients: [{client: 'Drainify',
        quotes: [{id: 9, updated_at: '2026-09-16'}]}]})}));
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await openRun();
  const resp = await p.textContent(hist.replace(' [data-pane="history"]', '')
    + ' [data-pane="history"] tr.histrow');
  say('reload.respIsNew', /1,111/.test(resp), resp.replace(/\s+/g, ' ').slice(0, 90));
  const card = await p.textContent(hist + ' .pview');
  say('reload.noUnmeasured', !/unmeasured/.test(card),
      (card.match(/Ranking[\s\S]{0,60}/) || [''])[0]);
  const kwText = await p.textContent(hist + ' .pvkw');
  say('reload.noFailedRows', !/—/.test(kwText.replace(/— not this/g, '')),
      'dashes still in the rank column');
  const tiles = await p.$$eval(hist + ' .qtile b', n => n.map(x => x.textContent));
  say('reload.tilesAreNew', tiles.join('/') === '$1,111/$2,222/$3,333', tiles.join('/'));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
