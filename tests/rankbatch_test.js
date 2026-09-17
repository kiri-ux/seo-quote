// THE RANK CHECK STOPPED WAITING IN LINE.
//
// Step 3 is the slowest part of a build, and it was slow for one reason: the
// batches were awaited one after another, so the batch size WAS the number of
// sequential round trips. Throughput was never the limit -- SERP sits in the
// 300/min family and a whole build spends about 39 -- it was the waiting.
//
// Firing them together changes three things that the rest of the quote depends
// on, and each is checked here rather than assumed:
//   * the batches no longer finish in the order they were sent, so the proposal
//     table has to be sorted back into the order the keywords were asked in;
//   * the progress counter has to count COMPLETIONS, because position in the
//     list no longer says how far along the check is;
//   * a throw used to abort the loop and lose every batch after it. Now the
//     others have already run, so their rows are kept and only the failed
//     batch's terms go to the unmeasured rerun.
//
// The slow batch here is the FIRST one, which is the case a sort would have
// hidden if the batches happened to come back in order anyway.
//
// Also on this screen: a recheck the run starts itself said nothing to anyone
// who opened the quote to look. The row line said "Rechecking 16 unmeasured
// terms...", the open quote said nothing at all, and a job still going read as
// one that died. (2026-09-17)
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

  // 45 terms: three batches of twenty, twenty and five.
  const N = 45;
  const batchesSeen = [];
  await p.route('**/api/rankings', async route => {
    const body = route.request().postDataJSON() || {};
    const kws = (body.batch || []).map(x => x.kw);
    batchesSeen.push(kws.length);
    const nth = kws.length ? Number(String(kws[0]).split(' ')[1]) / 20 : 0;
    // The first batch comes back LAST, and the second one throws.
    if (nth === 0) await new Promise(r => setTimeout(r, 700));
    if (nth === 1) return route.abort();
    return route.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify({results: kws.map(kw => ({
        kw, pos: 3, ranked_top: true, error: false}))})});
  });
  await p.route('**/api/price', route =>
    route.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify({handoff: {package: {base: 2900, intermediate: 3900,
                                                advanced: 4900}},
                            total_volume: 4690, pct_not_ranking: 0})}));
  await p.route('**/api/metrics', route =>
    route.fulfill({status: 200, contentType: 'application/json', body: '{"adder":0}'}));
  await p.route('**/api/market_signals', route =>
    route.fulfill({status: 200, contentType: 'application/json', body: '{}'}));
  await p.route('**/api/serp_**', route =>
    route.fulfill({status: 200, contentType: 'application/json', body: '{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout: 15000});

  const seen = [];
  const out = await p.evaluate(async n => {
    ROW = 0;
    const r = ROWS[0];
    r.kw = r.kw || {};
    r.kw.all = Array.from({length: n}, (_, i) => ({kw: 'term ' + i, vol: 100}));
    r.kw.head = r.kw.all.slice(0, 3);
    r.data = Object.assign({}, r.data, {g_city: 1, city: ['Boca Raton, FL'],
                                        brand: 'Drainify', site: 'drainify.com'});
    // Every progress line Step 3 painted, in the order it painted them.
    const lines = [];
    const saved = document.getElementById('saved');
    const mo = new MutationObserver(() => lines.push(saved.textContent));
    mo.observe(saved, {childList: true, characterData: true, subtree: true});
    await generate();
    mo.disconnect();
    const t = (r.result || {}).table || [];
    return {order: t.map(x => x.kw),
            n: t.length,
            errored: t.filter(x => x.error).length,
            lines: lines.filter(x => /Step 3/.test(x))};
  }, N);

  // Every term comes back, including the batch that threw.
  say('no batch is lost when one fails', out.n === N, out.n + ' of ' + N);
  say('and only that batch is unmeasured', out.errored === 20, out.errored);
  // THE POINT OF THE SORT. The first batch answered last; without the re-sort
  // the proposal would open on term 20.
  const asked = Array.from({length: N}, (_, i) => 'term ' + i);
  say('the table is in the order the keywords were asked in',
      out.order.join(',') === asked.join(','), out.order.slice(0, 3));
  // Three from the build. A fourth of ten follows it -- that is the automatic
  // rerun picking up the failed batch's terms, and it batches by its own size.
  say('the build sent three batches', batchesSeen.slice(0, 3).join(',') === '20,20,5',
      batchesSeen);
  // Counting completions, not position: the counter must never go backwards and
  // must finish on the full count.
  const nums = out.lines.map(l => (l.match(/(\d+)\/\d+/) || [])[1]).filter(Boolean).map(Number);
  say('progress never goes backwards',
      nums.every((v, i) => i === 0 || v >= nums[i - 1]), nums);
  // A FAILED BATCH IS STILL A FINISHED BATCH. Counting only the successes left
  // the line reading 25/45 with nothing left running.
  say('and ends on the whole list', nums[nums.length - 1] === N, nums);

  // ---- the recheck line reaches the open quote ----
  // The build above failed a batch, so the run started a recheck by itself.
  // That is exactly the state a planner opens the quote in.
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(300);
  const note = await p.evaluate(() => {
    const i = ROWS.indexOf(ROWS[0]);
    const el = document.querySelector(`.qnote[data-row="${i}"]`);
    if (!el) return {missing: true};
    // note() is a closure inside the run; drive the same two surfaces it does.
    const paint = t => document.querySelectorAll(`.qnote[data-row="${i}"]`)
      .forEach(n => { n.textContent = t; n.hidden = !t; });
    const before = {text: el.textContent, hidden: el.hidden};
    paint('Rechecking 20 unmeasured terms\u2026');
    return {before, text: el.textContent, shown: !el.hidden};
  });
  say('the open quote has somewhere to say it', !note.missing, note);
  // THE WHOLE COMPLAINT, END TO END. The run's own note() wrote this onto the
  // open quote with nothing in the test touching it -- before the fix the same
  // text reached the row line and this element did not exist.
  say('the run\'s own line is already on it',
      /\S/.test((note.before || {}).text || '') && (note.before || {}).hidden === false,
      note.before);
  say('the recheck line reaches it', /Rechecking 20 unmeasured/.test(note.text || ''), note);
  say('and it is unhidden once painted', note.shown === true, note);

  // note() itself paints both surfaces, which is the fix -- the stub above only
  // shows the open quote can carry the line.
  const src = await (await fetch('http://127.0.0.1:5203/adtini/forecast')).text();
  say('the open quote renders the line',
      /class="hint qnote" data-row=/.test(src), 'no qnote in qbody');
  say('and note() paints it alongside the row line',
      /\.qnote\[data-row="\$\{i\}"\]/.test(src) && /\.rowmsg/.test(src), 'note() misses one');

  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
