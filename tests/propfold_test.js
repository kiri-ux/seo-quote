// A SCREENSHOT IS NOT A VALUE, AND THREE THINGS THAT MOVED WITH IT.
//
// Opening the Proposal fold on any quote with a captured SERP broke the page.
// The field list prints every payload value as text, and `serp` IS the image --
// a base64 data URI, 440,000 characters with no spaces. One unbreakable token
// in a table cell, so the table could not wrap and stretched to 3.5 MILLION
// pixels, taking the open quote's layout with it. Every quote that ran long
// enough to capture a SERP had it; the only reason it was not caught is that a
// quote without a capture reads "not captured" and renders fine.
//
// Fixed on both sides. The value side stops printing data URIs -- what a
// planner is checking is whether the image is there, so it says that and gives
// the size. The CSS side makes a cell unbreakable regardless, because the next
// long token will not be a screenshot.
//
// Also here, from the same pass (2026-09-17):
//   * the partner cost under each tier price, small -- it is what Billing
//     charges and reading it meant opening the Order form fold;
//   * Order ID and Partner folded into "Fields for demo tool only", where the
//     ORM form already keeps them: in adtini they arrive with the order;
//   * the per-tier step override removed -- offered, not wanted.
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 140)));

  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };

  await p.route('**/api/**', r =>
    r.fulfill({status: 200, contentType: 'application/json', body: '{}'}));
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout: 15000});

  // ---- the break ----
  const out = await p.evaluate(() => {
    ROW = 0;
    const r = ROWS[0];
    r.result = r.result || {};
    // A captured SERP, the size a real one is.
    r.result.shot = 'data:image/png;base64,' + 'iVBORw0KGgoAAAANSUhEUg'.repeat(20000);
    r.result.serp = {kw: 'frozen seafood'};
    r.result.pricing = r.result.pricing || {};
    r.result.pricing.handoff = Object.assign({}, (r.result.pricing || {}).handoff, {
      package: {base: 6800, intermediate: 8400, advanced: 10000},
      partner_hard_cost: {base: 4420, intermediate: 5460, advanced: 6500}});
    r.openRun = 0; r.startTab = 'history';
    draw();
    const pane = document.querySelector('.prod[data-row="0"] [data-pane="history"]');
    const fold = [...pane.querySelectorAll('.qfold')]
      .find(x => /^Proposal/.test(x.querySelector('summary').textContent.trim()));
    fold.querySelector('summary').click();
    const row = [...fold.querySelectorAll('tr')].find(tr => /SERP — screenshot/.test(tr.textContent));
    const tables = [...pane.querySelectorAll('table.send')];
    return {
      label: fold.querySelector('summary').textContent.replace(/\s+/g, ' ').trim(),
      serpCell: (row.querySelectorAll('td')[1] || {}).textContent.trim(),
      widest: Math.max(...tables.map(t => Math.round(t.getBoundingClientRect().width))),
      pageWidth: document.documentElement.scrollWidth,
      win: window.innerWidth,
      tiles: [...pane.querySelectorAll('.qtile')].map(t => ({
        head: (t.querySelector('small') || {}).textContent,
        price: (t.querySelector('b') || {}).textContent,
        cost: (t.querySelector('u') || {}).textContent || null,
        w: Math.round(t.getBoundingClientRect().width)})),
    };
  });

  // THE QUOTE THAT BROKE IT: nine of nine, which means the capture is there.
  say('the fold still counts the screenshot as present',
      /9 of 9 fields/.test(out.label), out.label);
  say('the table stays on the page', out.widest < 2000, out.widest);
  say('and the page does not scroll sideways',
      out.pageWidth <= out.win, [out.pageWidth, out.win]);
  say('the screenshot row says it is there', /^captured/.test(out.serpCell), out.serpCell);
  say('and gives the size rather than the bytes',
      /\d+ KB$/.test(out.serpCell) && out.serpCell.length < 40, out.serpCell);
  // THE TILES ARE THE THING THE BREAK DESTROYED. Three across, not stacked.
  say('the tile row survives it', out.tiles.length === 3, out.tiles);
  say('and is still a row, not a column',
      out.tiles.every(t => t.w < out.win / 2), out.tiles.map(t => t.w));

  // ---- the partner cost on the tiles ----
  const costs = out.tiles.map(t => t.cost).join(' / ');
  say('each tier names what it costs us',
      costs === '$4,420 cost / $5,460 cost / $6,500 cost', costs);
  const prices = out.tiles.map(t => t.price).join(' / ');
  say('under the price, not instead of it',
      prices === '$6,800 / $8,400 / $10,000', prices);
  const sizes = await p.evaluate(() => {
    const t = document.querySelector('.prod[data-row="0"] [data-pane="history"] .qtile');
    const px = el => parseFloat(getComputedStyle(el).fontSize);
    return {price: px(t.querySelector('b')), cost: px(t.querySelector('u')),
            deco: getComputedStyle(t.querySelector('u')).textDecorationLine};
  });
  say('and smaller than it', sizes.cost < sizes.price / 1.7, sizes);
  say('with no underline, whatever tag it uses', sizes.deco === 'none', sizes.deco);
  // A quote with no partner figure stored grows no line rather than "$0 cost".
  const none = await p.evaluate(() => {
    const r = ROWS[0];
    delete r.result.pricing.handoff.partner_hard_cost;
    draw();
    return [...document.querySelectorAll('.prod[data-row="0"] [data-pane="history"] .qtile')]
      .map(t => !!t.querySelector('u'));
  });
  say('an unpriced quote grows no cost line', none.every(x => !x), none);

  // ---- the form ----
  const form = await p.evaluate(() => {
    const seo = document.getElementById('formSeo') || document.querySelector('form');
    const fold = [...document.querySelectorAll('#seoForm details.demofold, form details.demofold')];
    const inFold = f => !!f && !!f.querySelector('[data-k="order_no"]')
                             && !!f.querySelector('[data-k="partner"]');
    return {
      folds: fold.length,
      bothFolded: fold.filter(inFold).length,
      // and nothing left loose in a main grid
      loose: [...document.querySelectorAll('[data-k="order_no"],[data-k="partner"]')]
        .filter(i => !i.closest('details.demofold')).length,
      summaries: fold.map(f => f.querySelector('summary').textContent.trim()),
    };
  });
  say('both forms fold the demo fields', form.bothFolded === 2, form);
  say('and neither leaves one loose', form.loose === 0, form);
  const label = [...new Set(form.summaries)].join('|');
  say('under the label the ORM form already used',
      label === 'Fields for demo tool only', label);

  // ---- the override that was not wanted ----
  const cfg = await p.evaluate(() => {
    ROWS[0].cfg = {};
    cfgLoad(ROWS[0]);
    return [...document.querySelectorAll('#cfgGrid [data-c]')].map(i => i.dataset.c);
  });
  say('there is no per-tier step override', !cfg.includes('ov_step'), cfg);
  say('and the base override is still there', cfg.includes('ov_core'), cfg);

  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
