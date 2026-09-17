// WHAT THE PRICE IS MADE OF.
//
// Two runs of ENT Consultants an hour apart came out $3,100 and $2,950, and the
// planner had nothing on screen to say why. The whole difference was the
// zero-ranking band: the first was built on Greenwood, a town the client does
// not operate in, where they ranked for 1 of 11 terms -- 91% not ranking, the
// 80%+ band, +7%. The second was built on Oxford, their own market, where they
// rank 1st, 4th, 4th, 4th, 6th and 6th -- 6% not ranking, no uplift at all.
//
// Every number needed to say that was already in hand. `pricing` carries the
// anchor, the adder, the uplift and the volume add; /api/metrics returns
// twenty-five fields and this screen used exactly one of them (met.adder).
//
// The adder's BASIS is the part that cannot be left out. Three different things
// produce a number here -- a measured bid, organic difficulty when no bids
// exist anywhere, or a flat score -- and "$0 because clicks are cheap" is a
// different fact from "$0 because nothing could be measured".
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 140)));
  await p.goto('http://127.0.0.1:5199/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForTimeout(1800);

  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };

  const out = await p.evaluate(() => {
    // A FOLD, NOT MORE TILES. The tile row is the headline and four more cards
    // buried it; this is the working, read when a number is being questioned
    // and ignored the rest of the time.
    const view = (pricing, metrics) => {
      const r = {kind: 'seo', band: 'contiguous_region', data: {strategy: ['Core SEO']},
                 kw: {all: []},
                 result: {pricing, metrics, ranks: {}, quote: {totals: {}, handoff: {}}}};
      return priceFold(r);
    };
    return {
      // The Oxford run: a real bid, no uplift.
      oxford: view({anchor: 1850, competitive_adder: 0, zero_ranking_uplift_pct: 0,
                    pct_not_ranking: 6.2, volume_add: 0, total_volume: 180},
                   {adder_basis: 'cpc', cpc_used: 2.1, cpc_n_bids: 4}),
      // The Greenwood run: same anchor, +7%.
      greenwood: view({anchor: 1850, competitive_adder: 0, zero_ranking_uplift_pct: 7,
                       pct_not_ranking: 90.9, volume_add: 0, total_volume: 110},
                      {adder_basis: 'cpc', cpc_used: 2.1, cpc_n_bids: 4}),
      // No bids anywhere: difficulty decided it, and the line must say so.
      kd: view({anchor: 1850, competitive_adder: 150, zero_ranking_uplift_pct: 0,
                pct_not_ranking: 10, volume_add: 0, total_volume: 180},
               {adder_basis: 'kd', median_kd: 45}),
      // Nothing measured at all is its own fact, not a $0 verdict.
      none: view({anchor: 1850, competitive_adder: 0, zero_ranking_uplift_pct: 0,
                  pct_not_ranking: 10, volume_add: 0, total_volume: 180}, {}),
      // A quote priced before this panel shipped: real adder, no stored basis.
      legacy: view({anchor: 5450, competitive_adder: 550, zero_ranking_uplift_pct: 0,
                    pct_not_ranking: 10, volume_add: 0, total_volume: 4690}, {}),
      // An ORM quote has no geo anchor and must not grow empty rows.
      orm: (() => {
        const r = {kind: 'orm', data: {}, kw: {},
                   result: {pricing: {}, quote: {totals: {}, handoff: {}}}};
        return priceFold(r);
      })(),
      // The tile row must NOT carry them any more -- that is the whole change.
      tiles: (() => {
        const r = {kind: 'seo', band: 'contiguous_region', data: {strategy: ['Core SEO']},
                   kw: {all: []},
                   result: {pricing: {anchor: 1850, competitive_adder: 0,
                                      zero_ranking_uplift_pct: 0, pct_not_ranking: 6.2,
                                      volume_add: 0, total_volume: 180},
                            metrics: {adder_basis: 'cpc', cpc_used: 2.1},
                            ranks: {}, quote: {totals: {}, handoff: {}}}};
        const v = plannerView(r, false);
        return (v && v.html) || String(v);
      })(),
    };
  });

  const has = (h, t) => h.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').includes(t);

  say('the anchor is named with its scope',
      has(out.oxford, 'Geo anchor') && has(out.oxford, '$1,850')
      && has(out.oxford, 'contiguous region'), out.oxford.slice(0, 300));
  say('the adder names the bid it was measured from',
      has(out.oxford, 'median top-of-page bid $2.10'), out.oxford.slice(0, 300));
  say('and how many bids stood behind it',
      has(out.oxford, '4 bids'), out.oxford.slice(0, 300));

  // The two runs differ in exactly one row. That is the whole point of the panel.
  say('no uplift reads as 0%', has(out.oxford, '0%'), out.oxford.slice(0, 400));
  say('the uplift is signed when it applies',
      has(out.greenwood, '+7%'), out.greenwood.slice(0, 400));
  say('and carries the fraction that produced it',
      has(out.greenwood, '91% of measured terms not ranking'), out.greenwood.slice(0, 400));

  // A $0 adder has two very different causes and they must not read alike.
  say('difficulty is named when it decided the adder',
      has(out.kd, 'organic difficulty 45/100') && has(out.kd, 'no bid data'),
      out.kd.slice(0, 300));
  say('and an unmeasured adder says so rather than showing $0 alone',
      has(out.none, 'not measured'), out.none.slice(0, 300));
  // BUT ONLY WHEN THERE IS NOTHING TO REPORT. A real adder with no stored basis
  // -- every quote priced before this panel existed -- must not be labelled
  // "not measured"; $550 measured as nothing is a contradiction, and it is
  // what the first version of this line printed.
  say('a real adder with no stored basis claims nothing',
      has(out.legacy, '$550') && !has(out.legacy, 'not measured'),
      out.legacy.slice(0, 300));

  say('volume shows the add and the demand behind it',
      has(out.oxford, 'Volume add') && has(out.oxford, '180/mo'), out.oxford.slice(0, 400));
  // ORM prices on a different model entirely; these rows would be noise.
  say('an ORM quote grows no pricing rows',
      !has(out.orm, 'Geo anchor') && !has(out.orm, 'Competitive adder'),
      out.orm.slice(0, 200));
  // It is a fold, and it is closed until someone wants it.
  say('it renders as a collapsible fold',
      out.oxford.includes('<details') && has(out.oxford, 'Pricing'), out.oxford.slice(0, 120));
  say('and does not start open', !out.oxford.includes('<details open'), out.oxford.slice(0, 120));
  // The headline tiles stay the headline.
  say('the tile row no longer carries the breakdown',
      !has(out.tiles, 'Geo anchor') && !has(out.tiles, 'Competitive adder'),
      out.tiles.slice(0, 300));
  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
