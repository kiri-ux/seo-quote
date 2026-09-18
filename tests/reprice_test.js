// A PRICE CHANGE IS NOT A NEW FORECAST.
//
// Moving the markup or typing an override ran the whole pipeline again -- the
// keyword list rebuilt, competition scored, twenty-five rankings checked --
// minutes of API calls to move a number that is arithmetic off measurements
// already in hand. On the config pane the button now reads Reprice and calls
// /api/price alone.
//
// And it sends every override the pane offers: AI Search and add-on market had
// boxes on that pane since it shipped and neither was ever put on the request,
// so typing $1,787.50 against AI Search changed nothing and the quote came
// back at the built-in 74% of Core SEO. (2026-09-18, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

const PRICE = {
  anchor: 5450, base: 5450, step: 50, min_term_months: 6,
  total_volume: 4690, pct_not_ranking: 67, competitive_adder: 550,
  handoff: {package: {base: 7400, intermediate: 10200, advanced: 13050},
            core_seo_price: {base: 4250, intermediate: 5850, advanced: 7500},
            margin_pct: 0.35,
            partner_hard_cost: {base: 4800, intermediate: 6600, advanced: 8450}},
};

// The file defaults the pane loads, so an untouched field reads as untouched.
const CFG = {
  grid_target_keywords: 32, grid_min_services: 7, grid_max_services: 20,
  grid_max_cities: 5, grid_state_suffix: 'auto', service_min_volume: 30,
  service_upgrade_ratio: 10, service_max_swaps: 3, store_intent_tier_boost: 3,
  expand_min_volume: 20,
  cpc_adder_mult: 2.6, cpc_adder_cap: 1300, cpc_adder_knee: 62,
  cpc_adder_mult_high: 12.3, tier_step_pct_of_base: 0.24, cpc_adder_free_below: 5,
  bid_score_breaks: [5, 15], competitive_adder: {0: 0, 1: 150, 2: 250},
  zero_ranking_tiers: [[80, 7], [65, 4], [50, 2], [0, 0]], zero_ranking_top_n: 100,
  vol_free_below: 10000, vol_add_ramp: [40, 60],
  volume_brackets: [[10000, 20000, 0.0702], [20000, 35000, 0.0439],
                    [35000, null, 0.0351]],
  geo_anchor: {single_city: 2250, contiguous_region: 1850,
               non_contiguous_region: 2050, statewide: 2100, nationwide: 1800},
  tier_step_flat: 650, step_ratio: 0.38, volume_add_cap: 450, client_floor: 2950,
  default_markup_pct: 35, nationwide_service_extras: 1,
  geo_pct_tiers: [[90, 74], [70, 66], [40, 59], [0, 48]], geo_pct_default: 57,
  min_term_months: 6, pin_head_terms: 3, pin_min_volume: 300,
};

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const errs = [];
  const calls = [];
  p.on('pageerror', e => errs.push(e.message));
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };

  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    let body = {};
    try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    calls.push({url, body});
    const out = url === '/api/price' ? PRICE
              : url === '/api/config' ? CFG : {};
    route.fulfill({status: 200, contentType: 'application/json',
                   body: JSON.stringify(out)});
  });

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod[data-row="0"] .qres');

  // A row with a quote already on it, and the request that priced it.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'seo';
    r.result = r.result || {};
    r.result.pricing = {anchor: 5450, pct_not_ranking: 67, total_volume: 4690,
                        handoff: {package: {base: 5450}}};
    r.result.priceReq = {band: 'single_city', adder: 550, zero_ranking: false,
                         addon_markets: 4, markup_pct: 35, pct_not_ranking: 67,
                         total_volume: 4690, industry: 'Dental',
                         ai_search: true, core_seo: true,
                         national_demand: false, pageone_rank: null};
    r.result.over = {};
    r.history = [{when: 'now', resp: 'old', quote: r.result}];
    draw();
  });

  await p.click('[data-open="0"][data-view="cfg"]');
  await p.waitForSelector('#cfgGlobal [data-g="geo_anchor.single_city"]');
  say('a priced quote reprices rather than regenerating',
      (await p.textContent('#gen')).trim() === 'Reprice', await p.textContent('#gen'));

  // A LIST-SHAPING CONSTANT CANNOT BE REPRICED INTO A QUOTE. Step 1 builds the
  // keyword list and step 2 measures competition; step 4 is handed both. So
  // the button has to go back to saying the whole run.
  const was = await p.evaluate(() => ({
    grid: document.querySelector('#cfgGlobal [data-g="grid_target_keywords"]').value,
    cap: document.querySelector('#cfgGlobal [data-g="cpc_adder_cap"]').value}));
  await p.fill('#cfgGlobal [data-g="grid_target_keywords"]', '40');
  await p.waitForTimeout(100);
  say('a keyword-grid edit needs the whole run',
      (await p.textContent('#gen')).trim() === 'Regenerate Quote',
      await p.textContent('#gen'));
  await p.fill('#cfgGlobal [data-g="grid_target_keywords"]', was.grid);
  await p.fill('#cfgGlobal [data-g="cpc_adder_cap"]', '1500');
  await p.waitForTimeout(100);
  say('and so does a competition-adder edit',
      (await p.textContent('#gen')).trim() === 'Regenerate Quote',
      await p.textContent('#gen'));
  await p.fill('#cfgGlobal [data-g="cpc_adder_cap"]', was.cap);
  await p.waitForTimeout(100);

  // A PRICING CONSTANT IS PURE ARITHMETIC, and so are the override boxes.
  await p.fill('#cfgGlobal [data-g="geo_anchor.single_city"]', '2400');
  await p.waitForTimeout(100);
  say('an anchor edit reprices', (await p.textContent('#gen')).trim() === 'Reprice',
      await p.textContent('#gen'));

  await p.evaluate(() => {
    const set = (k, v) => { document.querySelector(`#cfgGrid [data-c="${k}"]`).value = v; };
    set('markup', '40');
    set('min_term', '12');
    set('addon_markets', '2');
    set('ov_core', '2762.5');
    set('ov_ai', '1787.5');
    set('ov_addon', '45');
    set('ov_reason', 'competitive market');
  });
  calls.length = 0;
  await p.click('#gen');
  await p.waitForFunction(() => document.getElementById('scrim').hidden,
                          null, {timeout: 15000});

  const priced = calls.filter(c => c.url === '/api/price');
  say('one pricing call', priced.length === 1, JSON.stringify(calls.map(c => c.url)));
  say('and nothing is measured again',
      !calls.some(c => /keywords|refine|metrics|rankings|site_services|market_signals/
                       .test(c.url)), JSON.stringify(calls.map(c => c.url)));

  const req = (priced[0] || {}).body || {};
  say('the AI Search override is sent', req.geo_override === '1787.5',
      JSON.stringify(req.geo_override));
  say('the add-on market override is sent', req.addon_override === '45',
      JSON.stringify(req.addon_override));
  say('the Core SEO override is sent', req.base_override === '2762.5',
      JSON.stringify(req.base_override));
  say('the markup is the one on the quote', req.markup_pct === 40, String(req.markup_pct));
  say('the market count is the one set in config', req.addon_markets === 2,
      String(req.addon_markets));
  say('the minimum term rides on the quote cfg',
      (req.cfg || {}).min_term_months === 12, JSON.stringify(req.cfg));
  say('the anchor edit rides with it',
      Number(((req.cfg || {}).geo_anchor || {}).single_city) === 2400,
      JSON.stringify(req.cfg));
  // WHAT WAS MEASURED IS NOT RE-GUESSED. The adder, the volume and the share of
  // terms not ranking are the run's own, or the reprice would quietly move the
  // price on inputs nobody re-measured.
  say('the measured inputs are the run’s own',
      req.adder === 550 && req.total_volume === 4690 && req.pct_not_ranking === 67,
      JSON.stringify([req.adder, req.total_volume, req.pct_not_ranking]));

  const after = await p.evaluate(() => ({
    tiers: (ROWS[0].result.pricing.handoff || {}).package,
    runIsTheSameQuote: ROWS[0].history[0].quote === ROWS[0].result,
    runLine: ROWS[0].history[0].resp,
    cfgRecorded: (ROWS[0].result.cfg || {}).ov_ai,
    overRecorded: Number(((ROWS[0].result.over || {}).geo_anchor || {}).single_city),
  }));
  say('the quote carries the new price', (after.tiers || {}).base === 7400,
      JSON.stringify(after.tiers));
  say('the run on screen is the quote that was just repriced',
      after.runIsTheSameQuote, JSON.stringify(after));
  say('and its line says the new price', /7,400/.test(after.runLine || ''),
      after.runLine);
  say('the run records what it was priced on',
      after.cfgRecorded === '1787.5' && after.overRecorded === 2400,
      JSON.stringify(after));

  say('no page errors', errs.length === 0, JSON.stringify(errs));
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
