// A FINISHED BUILD LANDS ON ITS OWN QUOTE.
//
// Generate dropped you back on Details with the run collapsed, so the thing you
// just waited four minutes for took two more clicks to see: History, then open
// the top row. The review link has landed this way since it shipped -- newest
// run, already expanded -- and the planner who built it had to do it by hand.
//
// The pin is the part that needs watching. startTab beats tab on every redraw,
// which is what makes the landing survive the draw() the SERP capture fires a
// minute later. Left set, that same rule throws a planner who has since chosen
// Details back to History. So choosing a tab by hand ends it. (2026-09-17)
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

  await p.route('**/api/rankings', route => {
    const kws = ((route.request().postDataJSON() || {}).batch || []).map(x => x.kw);
    return route.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify({results: kws.map(kw => ({kw, pos: 3, ranked_top: true,
                                                     error: false}))})});
  });
  await p.route('**/api/metrics', route =>
    route.fulfill({status: 200, contentType: 'application/json', body: '{"adder":0}'}));
  await p.route('**/api/market_signals', route =>
    route.fulfill({status: 200, contentType: 'application/json', body: '{}'}));
  await p.route('**/api/price', route =>
    route.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify({handoff: {package: {base: 3800, intermediate: 5250,
                                                advanced: 6700}},
                            total_volume: 51690, pct_not_ranking: 0})}));
  await p.route('**/api/serp_**', route =>
    route.fulfill({status: 200, contentType: 'application/json', body: '{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout: 15000});

  const after = await p.evaluate(async () => {
    ROW = 0;
    const r = ROWS[0];
    r.kw = r.kw || {};
    r.kw.all = Array.from({length: 6}, (_, i) => ({kw: 'term ' + i, vol: 100}));
    r.kw.head = r.kw.all.slice(0, 3);
    r.data = Object.assign({}, r.data, {g_city: 1, city: ['Boca Raton, FL'],
                                        brand: 'Drainify', site: 'drainify.com'});
    await generate();
    const prod = document.querySelector('.prod[data-row="0"]');
    const on = prod.querySelector('.ptabs button.on');
    return {
      tab: on && on.dataset.tab,
      historyShown: !prod.querySelector('[data-pane="history"]').hidden,
      detailsShown: !prod.querySelector('[data-pane="details"]').hidden,
      // The run's own body, the one the open button builds.
      openRows: prod.querySelectorAll('.hist .qbody').length,
      openRun: r.openRun,
      // The modal it was built in is gone.
      scrimHidden: document.getElementById('scrim').hidden,
      headline: (prod.querySelector('.hist .qbody .tile b, .hist .qbody .tile strong')
                 || {}).textContent || '',
    };
  });

  say('lands on History', after.tab === 'history' && after.historyShown, after);
  say('and not on Details', after.detailsShown === false, after);
  say('with the newest run expanded', after.openRun === 0 && after.openRows === 1, after);
  say('and the build modal closed behind it', after.scrimHidden === true, after);

  // THE PIN LETS GO. A redraw a minute later -- the SERP capture landing -- must
  // not undo a tab the planner has since chosen.
  const switched = await p.evaluate(() => {
    const prod = document.querySelector('.prod[data-row="0"]');
    prod.querySelector('.ptabs button[data-tab="details"]').click();
    draw();
    const p2 = document.querySelector('.prod[data-row="0"]');
    const on = p2.querySelector('.ptabs button.on');
    return {tab: on && on.dataset.tab,
            detailsShown: !p2.querySelector('[data-pane="details"]').hidden,
            startTab: ROWS[0].startTab};
  });
  say('choosing Details sticks through a redraw',
      switched.tab === 'details' && switched.detailsShown === true, switched);
  say('and the pin is cleared, not just overridden', !switched.startTab, switched);

  // And the run is still open underneath, so going back to History shows it.
  const back = await p.evaluate(() => {
    const prod = document.querySelector('.prod[data-row="0"]');
    prod.querySelector('.ptabs button[data-tab="history"]').click();
    const open = prod.querySelectorAll('.hist .qbody').length;
    // Collapsed, so the count above is a count of something.
    prod.querySelector('.hist [data-hist]').click();
    return {open, collapsed: document
      .querySelector('.prod[data-row="0"]').querySelectorAll('.hist .qbody').length};
  });
  say('the run stays open when you come back', back.open === 1, back);
  say('and collapses to nothing when closed', back.collapsed === 0, back);

  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
