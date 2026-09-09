// THE IO FIELD LIST IS OURS, NOT THE REVIEWER'S.
//
// Two long internal tables sat open above the proposal on every copy of the
// quote, including the one sent out for review. Folded, and closed until
// somebody opens them. (2026-09-08, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    ST.kw = { all: [], ultra: [], competitive: [], long_tail: [] };
    ST.table = [];
    ST.pricing = { handoff: {
      package: { base: 2950 }, core_seo_price: { base: 2950 },
      ai_search_price: { base: 0 }, addon_market_price: { base: 2655 },
      partner_addon_market_cost: { base: 1720 }, ai_search_pct: 0,
      margin_pct: 35, addon_market_discount_pct: 10, addon_markets: 1,
      partner_hard_cost: { base: 1900 }, partner_core_seo_cost: { base: 1900 },
      partner_ai_search_cost: { base: 0 }, margin_dollars: { base: 1050 },
    } };

    const host = document.createElement('div');
    document.body.appendChild(host);

    const REAL = window.REVIEW_MODE;
    host.innerHTML = handoffChart();
    const d1 = host.querySelector('details.iofold');
    R.isFolded = !!d1;
    R.openForPlanner = d1 ? d1.open : null;
    R.summaryText = d1 ? (d1.querySelector('summary').textContent || '').trim() : '';
    R.holdsBothTables = d1 ? (d1.querySelectorAll('table').length >= 2) : false;
    R.proposalFieldsInside = d1
      ? /the proposal fields/i.test(d1.textContent || '') : false;
    return R;
  });

  // REVIEW_MODE is read off the path, so the closed case is checked on a page
  // loaded exactly as a reviewer loads it.
  const p2 = await b.newPage();
  await p2.goto('http://127.0.0.1:5199/review/tok123',
                { waitUntil: 'domcontentloaded' });
  const closed = await p2.evaluate(async () => {
    ST.kw = { all: [], ultra: [], competitive: [], long_tail: [] };
    ST.table = [];
    ST.pricing = { handoff: { package: { base: 2950 }, margin_pct: 35,
                              addon_markets: 1 } };
    const host = document.createElement('div');
    document.body.appendChild(host);
    host.innerHTML = handoffChart();
    const d = host.querySelector('details.iofold');
    return { present: !!d, open: d ? d.open : null, mode: REVIEW_MODE };
  });

  let fail = [];
  const check = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? '  ok   ' : '  FAIL ') + label);
    if (!ok) { console.log('         got  ' + JSON.stringify(got) +
                           '\n         want ' + JSON.stringify(want)); fail.push(label); }
  };

  console.log('IT FOLDS');
  check('the block is a details', out.isFolded, true);
  check('the heading is the control', /Sent to the IO/i.test(out.summaryText), true);
  check('and both IO tables are inside it', out.holdsBothTables, true);
  check('including the proposal fields', out.proposalFieldsInside, true);

  console.log('\nCLOSED UNTIL SOMEBODY WANTS IT');
  check('closed on the working copy', out.openForPlanner, false);
  check('the review page really is in review mode', closed.mode, true);
  check('present on the review copy', closed.present, true);
  check('and closed there too', closed.open, false);

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
