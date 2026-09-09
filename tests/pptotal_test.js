// THE HEADLINE WAS NOT THE INVOICE.
//
// The proposal's three cards showed the primary market alone -- $2,950 --
// while the table directly below them totalled the add-on markets in at
// $5,605. The first number on the page was not the number the client pays, and
// the only way to set the add-on count was on the other tab. (2026-09-08, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const priced = n => ({
      anchor: 1800, base: 1850, markup_pct: 35, addon_markets: n,
      competitive_adder: 50, volume_add: 0, min_term_months: 6,
      client_tiers: { base: 2950, intermediate: 4000, advanced: 5100 },
      client_addon_per_market: n ? { base: 2655, intermediate: 3600, advanced: 4590 }
                                 : { base: 2950, intermediate: 4000, advanced: 5100 },
      client_addon_list_per_market: { base: 2950, intermediate: 4000, advanced: 5100 },
      addon_discount_pct: n ? 10 : 0,
      handoff: { addon_markets: n },
    });
    let asked = null;
    const real = window.fetch;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/price')) {
        asked = JSON.parse(o.body);
        const pay = priced(Number(asked.addon_markets || 0) || 0);
        return { ok: true, status: 200, text: async () => JSON.stringify(pay),
                 json: async () => pay };
      }
      if (String(u).includes('/api/perf_quote')) {
        const pay = { eligible: false };
        return { ok: true, status: 200, text: async () => JSON.stringify(pay),
                 json: async () => pay };
      }
      return real(u, o);
    };

    ST.inputs = { brand: 'Drainify', strategy: 'Core SEO', addon_markets: 1,
                  markup_pct: 35, geo_scope: 'nationwide', geo_values: [] };
    ST.kw = { all: [], ultra: [], competitive: [], long_tail: [] };
    ST.table = [];
    ST.pricing = priced(1);
    renderProposal();

    const amt = [...document.querySelectorAll('#ppTiers .amt')]
      .map(e => e.textContent.trim());
    R.cards = amt;
    R.showsTheSplit = /\+ 1 add-on market/.test(
      document.getElementById('ppTiers').textContent || '');
    R.hasControl = !!document.getElementById('ppAddonN');
    R.controlValue = (document.getElementById('ppAddonN') || {}).value;

    // the grid under it carries the add-on rows
    const built = document.getElementById('proposalView').textContent || '';
    R.gridHasAddons = /Add-on markets/.test(built);
    R.gridHasRate = /10% off/.test(built);
    R.gridTotal = /Base monthly investment/.test(built);

    // and the control drives the count. The Build tab's own field may not be
    // rendered yet -- the proposal tab can be opened first on a reopened quote
    // -- so it is synced only when it is there.
    const stub = document.createElement('input');
    stub.id = 'addon'; stub.value = '1';
    document.body.appendChild(stub);
    document.getElementById('ppAddonUp').click();
    R.afterUpInputs = ST.inputs.addon_markets;
    R.afterUpBuildField = (document.getElementById('addon') || {}).value;
    await new Promise(r => setTimeout(r, 900));
    R.repricedAt = asked ? asked.addon_markets : null;
    R.cardsAfter = [...document.querySelectorAll('#ppTiers .amt')]
      .map(e => e.textContent.trim());
    window.fetch = real;
    return R;
  });

  let fail = [];
  const check = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? '  ok   ' : '  FAIL ') + label);
    if (!ok) { console.log('         got  ' + JSON.stringify(got) +
                           '\n         want ' + JSON.stringify(want)); fail.push(label); }
  };

  console.log('THE CARDS ARE THE TOTAL');
  check('primary + one add-on market',
        out.cards, ['$5,605', '$7,600', '$9,690']);
  check('with the split named underneath', out.showsTheSplit, true);

  console.log('\nTHE COUNT IS SETTABLE FROM HERE');
  check('the control is on the proposal', out.hasControl, true);
  check('showing the current count', out.controlValue, '1');
  check('pressing + moves the quote', out.afterUpInputs, 2);
  check('and the Build tab field with it', out.afterUpBuildField, '2');
  check('a re-price is asked for the new count', out.repricedAt, 2);
  check('and the cards follow', out.cardsAfter,
        ['$8,260', '$11,200', '$14,280']);

  console.log('\nTHE PRICE GRID SPELLS THE ADD-ONS OUT');
  check('the row is there', out.gridHasAddons, true);
  check('with the rate that made it', out.gridHasRate, true);
  check('and a total under it', out.gridTotal, true);

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
