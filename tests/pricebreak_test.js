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
    const view = (pricing, metrics, health) => {
      const r = {kind: 'seo', band: 'contiguous_region', data: {strategy: ['Core SEO']},
                 kw: {all: []},
                 result: {pricing, metrics, health: (health || {}),
                          ranks: {}, quote: {totals: {}, handoff: {}}}};
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
                    pct_not_ranking: 10, volume_add: 0, total_volume: 4690}, {}, {}),
      // An ORM quote has no geo anchor and must not grow empty rows.
      orm: (() => {
        const r = {kind: 'orm', data: {}, kw: {},
                   result: {pricing: {}, quote: {totals: {}, handoff: {}}}};
        return priceFold(r);
      })(),
      // AND HOW THE MONTHLY WAS REACHED. The ORM fold named each line and its
      // price and stopped there, so "how did you get to $5,400/mo?" had no
      // answer on the page. Each line carries its own working now.
      ormBuild: (() => {
        const r = {kind: 'orm', data: {}, kw: {}, result: {pricing: {}, quote: {
          lines: [{service: 'Reactive \u00b7 Search Protection', kind: 'monthly',
                   detail: '500/mo measured', total: 5400, hard_total: 3480,
                   build: [{label: 'Organic search suppression',
                            value: '$1,100 base + $25.80/1K \u00d7 500/mo = $1,150'},
                           {label: 'Client price',
                            value: '$3,480 \u00f7 (1 \u2212 35%) \u2192 $5,400/mo'},
                           {label: 'Nothing to say', value: ''}]},
                  // A line with no stored working prints none -- quotes built
                  // before the pricer recorded it must not grow an empty box.
                  {service: 'Negative Review Removals', kind: 'per_asset',
                   detail: '11 flagged reviews', total: 9900, hard_total: 6435}],
          totals: {monthly: 5400, one_time: 9900},
          handoff: {margin_pct: 0.35, partner_monthly_cost: 3480}}}};
        return priceFold(r);
      })(),
      // SITE CONDITION. A measured site names the count and the worst offenders;
      // an unmeasured one says so rather than reading as clean, because a
      // blocked crawler and a spotless site are not the same fact.
      dirty: view({anchor: 1850, competitive_adder: 0, zero_ranking_uplift_pct: 0,
                   pct_not_ranking: 6.2, volume_add: 0, total_volume: 180,
                   site_debt: 6, site_debt_uplift_pct: 3},
                  {adder_basis: 'cpc', cpc_used: 2.1},
                  {checked: 18, score: 62.5,
                   failed: ['no H1', 'missing title', 'broken links', 'slow load',
                            'thin content']}),
      clean: view({anchor: 1850, competitive_adder: 0, zero_ranking_uplift_pct: 0,
                   pct_not_ranking: 6.2, volume_add: 0, total_volume: 180,
                   site_debt: 0, site_debt_uplift_pct: 0},
                  {adder_basis: 'cpc', cpc_used: 2.1},
                  {checked: 18, score: 96.0, failed: []}),
      unchecked: view({anchor: 1850, competitive_adder: 0, zero_ranking_uplift_pct: 0,
                       pct_not_ranking: 6.2, volume_add: 0, total_volume: 180},
                      {adder_basis: 'cpc', cpc_used: 2.1},
                      {error: 'the page returned nothing to check'}),
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
  // Scoped to the adder row: "not measured" legitimately appears further down
  // for a site that was never checked, which is a different row and a
  // different fact.
  const adderRow = h => (h.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ')
    .match(/Competitive adder adder ([^·]*?)(?: Zero-ranking| Site condition| Volume)/) || [])[1] || '';
  say('a real adder with no stored basis claims nothing',
      adderRow(out.legacy).includes('$550')
      && !adderRow(out.legacy).includes('not measured'), adderRow(out.legacy));
  // And a base that was never stored is omitted, not printed as $0.
  say('an unknown base is omitted rather than shown as $0',
      !/Base base \$0\b/.test(out.legacy.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ')),
      out.legacy.slice(-200));

  say('volume shows the add and the demand behind it',
      has(out.oxford, 'Volume add') && has(out.oxford, '180/mo'), out.oxford.slice(0, 400));
  // ORM prices on a different model entirely; these rows would be noise.
  say('an ORM quote grows no pricing rows',
      !has(out.orm, 'Geo anchor') && !has(out.orm, 'Competitive adder'),
      out.orm.slice(0, 200));
  say('a site with debt names the count and the uplift',
      has(out.dirty, '+3%') && has(out.dirty, '6 of 18 checks failing'),
      out.dirty.slice(0, 400));
  say('and the worst offenders, so it can be checked',
      has(out.dirty, 'no H1') && has(out.dirty, 'broken links'), out.dirty.slice(0, 500));
  say('a clean site is par, not a discount',
      has(out.clean, '0 of 18 checks failing') && has(out.clean, '96/100')
      && !/Site condition[^|]*[+-]\d+%/.test(out.clean.replace(/<[^>]*>/g, ' ')),
      out.clean.slice(0, 400));
  // The whole reason site_debt is nullable.
  say('an unchecked site says so rather than reading as clean',
      has(out.unchecked, 'not measured'), out.unchecked.slice(0, 400));
  // It is a fold, and it is closed until someone wants it.
  say('it renders as a collapsible fold',
      out.oxford.includes('<details') && has(out.oxford, 'Pricing'), out.oxford.slice(0, 120));
  say('and does not start open', !out.oxford.includes('<details open'), out.oxford.slice(0, 120));
  // The headline tiles stay the headline.
  say('the tile row no longer carries the breakdown',
      !has(out.tiles, 'Geo anchor') && !has(out.tiles, 'Competitive adder'),
      out.tiles.slice(0, 300));
  // THE WORKING, UNDER THE LINE IT BELONGS TO.
  say('each priced line shows its own arithmetic',
      has(out.ormBuild, '$1,100 base + $25.80/1K \u00d7 500/mo = $1,150'),
      out.ormBuild.slice(0, 600));
  say('including the margin step that reaches the client price',
      has(out.ormBuild, '$3,480 \u00f7 (1 \u2212 35%) \u2192 $5,400/mo'),
      out.ormBuild.slice(0, 600));
  say('a step with no value is left out rather than printed blank',
      !has(out.ormBuild, 'Nothing to say'), out.ormBuild.slice(0, 600));
  say('a line with no stored working grows no empty box',
      (out.ormBuild.match(/tr class="bld"/g) || []).length === 1,
      out.ormBuild.slice(0, 600));
  say('and the line itself still reads as before',
      has(out.ormBuild, 'Reactive \u00b7 Search Protection')
      && has(out.ormBuild, '$5,400/mo') && has(out.ormBuild, '$9,900'),
      out.ormBuild.slice(0, 600));
  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
