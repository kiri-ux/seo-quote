// THE CARDS MOVED AND NOTHING ELSE DID.
//
// The add-on stepper repaints the tier cards and the add-on table locally off
// the bracket schedule, so the Build tab was right the instant it was clicked.
// ST.pricing stayed the response computed with zero add-on markets, so the
// handoff table, the proposal tab, the saved quote and the .docx all read
// "Add-On Market Discount 0% - 0 markets" beside a Build tab showing 1 market
// at 10% off. (2026-09-08, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const priced = n => ({
      anchor: 1800, base: 1850, markup_pct: 35, addon_markets: n,
      client_tiers: { base: 2950, intermediate: 4000, advanced: 5100 },
      client_addon_per_market: n ? { base: 2655, intermediate: 3600, advanced: 4590 }
                                 : { base: 2950, intermediate: 4000, advanced: 5100 },
      addon_discount_pct: n ? 10 : 0,
      handoff: { addon_markets: n, addon_market_discount_pct: n ? 10 : 0,
                 addon_market_price: n ? { base: 2655 } : { base: 2950 } },
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
      return real(u, o);
    };

    ST.inputs = ST.inputs || {};
    ST.inputs.addon_markets = 0;
    ST.inputs.markup_pct = 35;
    ST.inputs.geo_scope = 'nationwide';
    ST.pricing = priced(0);
    R.before = ST.pricing.handoff.addon_markets;

    ST.inputs.addon_markets = 1;
    repriceForAddons();
    await new Promise(r => setTimeout(r, 900));
    R.sentCount = asked ? asked.addon_markets : null;
    R.after = (ST.pricing.handoff || {}).addon_markets;
    R.discountAfter = (ST.pricing.handoff || {}).addon_market_discount_pct;

    // holding the stepper must not fire one call per press
    asked = null; let calls = 0;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/price')) {
        calls++; asked = JSON.parse(o.body);
        const pay = priced(Number(asked.addon_markets || 0) || 0);
        return { ok: true, status: 200, text: async () => JSON.stringify(pay),
                 json: async () => pay };
      }
      return real(u, o);
    };
    for (let i = 2; i <= 6; i++) { ST.inputs.addon_markets = i; repriceForAddons(); }
    await new Promise(r => setTimeout(r, 900));
    R.callsForFivePresses = calls;
    R.landedOn = asked ? asked.addon_markets : null;
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

  console.log('THE STEPPER MOVES THE PRICING OBJECT');
  check('it starts at zero', out.before, 0);
  check('the re-price is asked for the new count', out.sentCount, 1);
  check('and the handoff carries it', out.after, 1);
  check('with the discount that goes with it', out.discountAfter, 10);

  console.log('\nHOLDING IT DOWN IS STILL ONE CALL');
  check('five presses, one re-price', out.callsForFivePresses, 1);
  check('and it lands on the last value', out.landedOn, 6);

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
