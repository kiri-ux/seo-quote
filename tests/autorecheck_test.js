// TWO CUTS TO THE RANK CHECK.
// 1. A term nobody searches is not sent to a SERP -- its rank changes no price.
// 2. The unmeasured rerun themselves, so "press Recheck" is not a manual step.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});

  // ---- the rule on its own ----
  const rule = await p.evaluate(() => {
    const mixed = [{kw:'a', vol:20}, {kw:'b', vol:0}, {kw:'c', vol:10},
                   {kw:'d', vol:0}];
    const allZero = [{kw:'a', vol:0}, {kw:'b', vol:0}];
    const noVol = [{kw:'a'}, {kw:'b', vol:null}];
    return {mixed: worthChecking(mixed).map(x => x.kw),
            allZero: worthChecking(allZero).map(x => x.kw),
            noVol: worthChecking(noVol).map(x => x.kw),
            empty: worthChecking([]).length};
  });
  say('zeroDemandDropped', rule.mixed.join('') === 'ac', JSON.stringify(rule.mixed));
  say('thinMarketStillChecked', rule.allZero.join('') === 'ab',
      JSON.stringify(rule.allZero));
  say('unmeasuredVolumeStillChecked', rule.noVol.length === 2,
      JSON.stringify(rule.noVol));
  say('emptyStaysEmpty', rule.empty === 0);

  // ---- and the recheck honours it, then finishes by itself ----
  let asked = [];
  await p.route('**/api/rankings', route => {
    const batch = ((route.request().postDataJSON() || {}).batch || []).map(x => x.kw);
    asked = asked.concat(batch);
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({results: batch.map(kw => ({
        kw, pos: 4, ranked_top: true, error: false}))})});
  });
  await p.route('**/api/price', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({handoff:{package:{base:2900,intermediate:3900,advanced:4900}},
                            total_volume: 40, pct_not_ranking: 0})}));
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));

  await p.evaluate(() => {
    const r = ROWS[0];
    r.kw = {all: [{kw:'hearing aids oxford ms', vol:20},
                  {kw:'pediatric ent surgery batesville ms', vol:0},
                  {kw:'tonsillectomies oxford ms', vol:10},
                  {kw:'pediatric ent surgery grenada ms', vol:0}]};
    r.result = r.result || {};
    r.result.ranks = {};
    r.result.table = r.kw.all.map(x => ({kw:x.kw, pos:'—', ranked_top:false,
                                         error:true}));
    r.result.table.forEach(x => { r.result.ranks[x.kw.toLowerCase()] = '—'; });
    r.data.g_city = 1; r.data.city = ['Oxford, MS'];
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(300);
  const hist = '.prod[data-row="0"] [data-pane="history"]';
  await p.click(hist + ' [data-recheck]');
  for (let i = 0; i < 30 && !/still failing|already has|measured/.test(
         await p.textContent(hist + ' [data-rkmsg]').catch(() => '')); i++)
    await p.waitForTimeout(400);
  await p.waitForTimeout(600);

  say('onlyDemandWasAsked',
      asked.every(k => !/pediatric ent surgery/.test(k)), JSON.stringify(asked));
  say('bothDemandTermsAsked',
      asked.includes('hearing aids oxford ms')
      && asked.includes('tonsillectomies oxford ms'), JSON.stringify(asked));
  const tbl = await p.evaluate(() => ROWS[0].result.table.map(x => x.kw));
  say('tallyDropsTheZeroRows', tbl.length === 2, JSON.stringify(tbl));

  // ---- the run kicks the recheck off itself ----
  const src = await p.evaluate(() => generate.toString());
  say('runRerunsTheUnmeasured', /recheckRanks\(ROWS\.indexOf\(r\)\)/.test(src));
  say('rerunComesBeforeTheCapture',
      src.indexOf('recheckRanks(ROWS.indexOf(r))') < src.indexOf('autoSerp(r, d, ranks'),
      'the capture should photograph a term that has a rank');
  say('rerunOnlyWhenSomethingFailed', /errored\s*\n?\s*\?/.test(src) || /const rerun = errored/.test(src));

  // A ROW THAT WAS NEVER GOING TO BE CHECKED IS NOT AN UNMEASURED ROW.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kw = {all: [{kw:'a', vol:20}, {kw:'b', vol:10},
                  {kw:'z1', vol:0}, {kw:'z2', vol:0}, {kw:'z3', vol:0}]};
    r.result = r.result || {};
    r.result.ranks = {a: 4, b: '\u2014'};
    r.result.table = [{kw:'a', pos:4, ranked_top:true, error:false},
                      {kw:'b', pos:'\u2014', ranked_top:false, error:true}];
    r.result.pricing = {package:{base:2900,intermediate:3900,advanced:4900},
                        total_volume: 30, pct_not_ranking: 0};
    draw();
  });
  await p.waitForTimeout(400);
  const card = await p.$$eval('.prod[data-row="0"] .pv', ns =>
    ns.map(n => n.textContent).find(t => /^Ranking/.test(t)) || '');
  say('measuredCountIsWhatWasChecked', /1 of 1 measured term ranking/.test(card), card);
  say('unmeasuredCountsOnlyTheChecked', /1 unmeasured/.test(card), card);
  say('skippedAreNamedForWhatTheyAre', /3 no demand/.test(card), card);
  say('noPhantomUnmeasured', !/4 unmeasured/.test(card), card);

  // The provider's wording is not a status line.
  const says = await p.evaluate(() => [
    captureSays("Invalid Field: 'task_id' - This task is not yet completed."),
    captureSays('Task In Queue'),
    captureSays('Task Not Found.'),
    captureSays(''),
    captureSays('Something else entirely')]);
  say('notCompletedIsPlain', says[0] === 'still rendering', says[0]);
  say('queuedIsPlain', says[1] === 'still rendering', says[1]);
  say('notFoundIsPlain', says[2] === 'queued', says[2]);
  say('blankStaysBlank', says[3] === '', says[3]);
  say('anythingElseIsKept', says[4] === 'Something else entirely', says[4]);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
