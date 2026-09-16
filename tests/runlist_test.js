// EACH RUN KEEPS ITS OWN LIST, AND ITS OWN MARKS.
// Every run drew its keyword list off the row's current list, so rebuilding to
// 13 terms made the 36-term run read "13 terms" and show the 13-term table.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});

  await p.evaluate(() => {
    const r = ROWS[0];
    const big = {all: Array.from({length: 36}, (_, i) => ({kw: 'big term ' + i, vol: 10}))};
    const small = {all: Array.from({length: 13}, (_, i) => ({kw: 'small term ' + i, vol: 10}))};
    const mk = n => ({pricing: {handoff:{package:{base:2950,intermediate:3950,advanced:4950}},
                                total_volume: n * 10, pct_not_ranking: 50},
                      ranks: {}, table: []});
    r.kw = small;                      // the row's CURRENT list
    r.seedSrc = {'small term 1': 'their site'};
    r.result = mk(13);
    r.history = [
      {when: 'now', quote: r.result, kw: small, seedSrc: r.seedSrc},
      {when: 'earlier', quote: mk(36), kw: big, seedSrc: {'big term 2': 'the industry'}},
      // A run saved before lists were kept: only its rank table names its terms.
      {when: 'older', quote: Object.assign(mk(5), {table: [
        {kw: 'old term a', pos: 3, ranked_top: true, error: false},
        {kw: 'old term b', pos: '—', ranked_top: false, error: true}]})},
    ];
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.waitForTimeout(300);

  const lines = await p.$$eval('.prod[data-row="0"] .hist tr.histrow td:nth-child(2)',
    ns => ns.map(n => n.textContent));
  say('newestSaysThirteen', /13 terms/.test(lines[0]), lines[0]);
  say('earlierStillSaysThirtySix', /36 terms/.test(lines[1]), lines[1]);
  say('olderReadsItsTable', /2 terms/.test(lines[2]), lines[2]);

  // Open the 36-term run: its table is its own.
  await p.click('.prod[data-row="0"] .hist tr.histrow[data-hist="1"] .btn-open');
  await p.waitForTimeout(300);
  const terms = await p.$$eval('.prod[data-row="0"] .histopen .kv tr:not(:first-child) td:first-child',
    ns => ns.map(n => n.textContent));
  say('openRunShowsItsOwnList', terms.length === 36 && /^big term/.test(terms[0]),
      terms.length + ' rows, first ' + JSON.stringify(terms[0]));

  // And that run's expansion mark, not the row's.
  const marked = await p.$$eval('.prod[data-row="0"] .histopen .kv tr.exp td:first-child',
    ns => ns.map(n => n.textContent));
  say('expansionRowMarkedInThatRun', marked.join('|') === 'big term 2', JSON.stringify(marked));

  // The older run reconstructs from its table.
  await p.click('.prod[data-row="0"] .hist tr.histrow[data-hist="2"] .btn-open');
  await p.waitForTimeout(300);
  const old = await p.$$eval('.prod[data-row="0"] .histopen .kv tr:not(:first-child) td:first-child',
    ns => ns.map(n => n.textContent));
  say('olderRunShowsItsTerms', old.join('|') === 'old term a|old term b', JSON.stringify(old));

  // The builder marks rows built from proposed seeds too.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kw = {ultra: [{kw:'small term 1 oxford', vol:10}, {kw:'typed term', vol:10}],
            competitive: [], long_tail: [], all: []};
    open(0, 'kw');
  });
  await p.waitForTimeout(300);
  const exp = await p.$$eval('#kbCols li.exp span:first-child', ns => ns.map(n => n.textContent));
  say('builderMarksExpansionRows', exp.join('|') === 'small term 1 oxford', JSON.stringify(exp));

  // A new run snapshots the list.
  const snap = await p.evaluate(() => {
    const src = generate.toString();
    return /kw: JSON\.parse\(JSON\.stringify\(r\.kw/.test(src) && /seedSrc: Object\.assign/.test(src);
  });
  say('newRunsKeepTheirList', snap);

  // A reload keeps the provenance.
  const back = await p.evaluate(() => {
    const src = loadClient.toString();
    return /seedSrc: a\.seedSrc/.test(src) && /seedDrop: a\.seedDrop/.test(src);
  });
  say('reloadKeepsTheMarks', back);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
