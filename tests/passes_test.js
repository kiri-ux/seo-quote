// ONE PRESS FINISHES THE JOB. The rank check runs under a budget the platform
// enforces at ~30s, so some lookups in a batch time out and come back as
// failures -- which is why pressing Recheck repeatedly kept reducing the count.
// And a redraw must not move you off the pane you were reading.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  // Every batch gets two through and times the rest out, the way a squeezed
  // CPU behaves. A repeating pass should still finish the list.
  const seen = [];
  let sizes = [];
  await p.route('**/api/rankings', route => {
    const body = route.request().postDataJSON() || {};
    const batch = (body.batch || []).map(x => x.kw);
    sizes.push(batch.length);
    seen.push(batch);
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({results: batch.map((kw, i) => i < 2
        ? {kw, pos: 'Not Found', ranked_top: false, error: false}
        : {kw, pos: '—', ranked_top: false, error: true})})});
  });
  await p.route('**/api/price', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({handoff:{package:{base:2900,intermediate:3900,advanced:4900}},
                            total_volume: 4690, pct_not_ranking: 100})}));
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
  await p.evaluate(() => {
    const r = ROWS[0];
    const seed = ((r.kw || {}).all || [])[0] || {kw: 'x', vol: 10};
    r.kw.all = Array.from({length: 12}, (_, i) =>
      Object.assign({}, seed, {kw: 'term ' + i}));
    r.result.ranks = {};
    r.result.table = r.kw.all.map(x => ({
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
  for (let i = 0; i < 30 && !/still failing|already has/.test(
         await p.textContent(hist + ' [data-rkmsg]').catch(() => '')); i++)
    await p.waitForTimeout(500);
  await p.waitForTimeout(800);

  say('batchesAreSmall', sizes.every(n => n <= 5), JSON.stringify(sizes));
  say('repeatedItself', sizes.length > 3, sizes.length + ' batches on one press');
  const ranks = await p.evaluate(() => Object.values(ROWS[0].result.ranks));
  const stillBad = ranks.filter(v => v === '—').length;
  say('finishedTheList', stillBad === 0, stillBad + ' of 12 still failing after one press');

  // AND IT LEFT YOU WHERE YOU WERE. A redraw used to rebuild the row on Details.
  say('stayedOnHistory',
      await p.$eval('.prod[data-row="0"] [data-pane="history"]', el => !el.hidden),
      'the redraw sent us back to Details');
  say('runStillOpen',
      (await p.$$eval(hist + ' tr.histopen', n => n.length)) === 1);
  say('historyTabStillOn',
      await p.$eval('.prod[data-row="0"] .ptabs button[data-tab="history"]',
                    el => el.classList.contains('on')));

  // THE CARD AGREES WITH THE LIST. The expanded run renders its own copy of the
  // quote, which the recheck was not updating.
  const card = await p.textContent(hist + ' .pview');
  say('cardNotStale', !/unmeasured/.test(card), card.match(/Ranking[^|]*/) || card.slice(0,80));

  // A pass that makes no progress stops rather than looping forever.
  sizes = [];
  await p.unroute('**/api/rankings');
  await p.route('**/api/rankings', route => {
    const body = route.request().postDataJSON() || {};
    const batch = (body.batch || []).map(x => x.kw);
    sizes.push(batch.length);
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({results: batch.map(kw => ({
        kw, pos: '—', ranked_top: false, error: true}))})});
  });
  await p.evaluate(() => {
    const r = ROWS[0];
    Object.keys(r.result.ranks).forEach(k => { r.result.ranks[k] = '—'; });
    r.result.table.forEach(x => { x.pos = '—'; x.error = true; });
    draw();
  });
  if (!(await p.$(hist + ' [data-recheck]')))
    await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForSelector(hist + ' [data-recheck]', {timeout:10000});
  await p.click(hist + ' [data-recheck]');
  for (let i = 0; i < 30; i++) {
    const t = await p.textContent(hist + ' [data-rkmsg]').catch(() => '');
    if (/still failing/.test(t)) break;
    await p.waitForTimeout(500);
  }
  say('stopsWhenStuck', sizes.length <= 6, sizes.length + ' batches with no progress');
  const m = await p.textContent(hist + ' [data-rkmsg]');
  say('saysHowManyStuck', /still failing/.test(m), m);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
