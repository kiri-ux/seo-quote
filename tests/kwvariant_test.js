// LOWER / HIGHER BUDGET ON A RUN.
//
// The two buttons ask for a swapped list, price it on the run's own
// measurements, show it beside the current price, and "Use this list" makes
// it the row's list so the next press is a full Regenerate. (2026-10-01, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 160)));
  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };
  const json = (route, o) => route.fulfill({status: 200,
    contentType: 'application/json', body: JSON.stringify(o)});
  let variantBody = null, priceBody = null;
  await p.route('**/api/kw_variant', route => {
    variantBody = route.request().postDataJSON();
    return json(route, {error: null, adder: 600, volume_delta: -1500,
      out: [{service: 'car accident attorney', cpc: 180, volume: 2050}],
      in: [{service: 'slip and fall lawyer', cpc: 60, volume: 160}],
      rows: [{kw: 'slip and fall lawyer seattle', vol: 80, city: 'seattle', tier: 'ultra'},
             {kw: 'dog bite lawyer seattle', vol: 90, city: 'seattle', tier: 'competitive'}]});
  });
  await p.route('**/api/price', route => {
    priceBody = route.request().postDataJSON();
    return json(route, {handoff: {package: {base: 9900, intermediate: 11500,
      advanced: 13200}}});
  });
  await p.goto('http://127.0.0.1:5203/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod[data-row="0"] .qres');

  await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'seo';
    r.kw = {ultra: [{kw: 'car accident attorney seattle', vol: 210, city: 'seattle'}],
            competitive: [{kw: 'dog bite lawyer seattle', vol: 90, city: 'seattle'}],
            long_tail: [], total_volume: 10250,
            pool: [{keyword: 'slip and fall lawyer', volume: 70}],
            service_volume: {'car accident attorney': 8000, 'dog bite lawyer': 2000}};
    r.kw.all = r.kw.ultra.concat(r.kw.competitive);
    r.kw.head = r.kw.all.slice();
    r.result = {pricing: {handoff: {package: {base: 13050, intermediate: 15350,
                                              advanced: 17600}}},
      metrics: {adder: 1300, cpc: {'car accident attorney': 180}},
      priceReq: {band: 'non_contiguous_region', adder: 1300, total_volume: 10250,
                 pct_not_ranking: 100, markup_pct: 35}, over: {}};
    r.history = [{when: 'now', resp: 'x', quote: r.result,
                  kw: JSON.parse(JSON.stringify(r.kw))}];
    r.openRun = 0; r.startTab = 'history';
    draw();
  });
  await p.waitForSelector('[data-variant="lower"][data-row="0"]', {timeout: 5000});
  // WHEN TO LOOK. One service holding most of the demand flags Lower.
  const flag = await p.textContent('[data-variant="lower"][data-row="0"]');
  say('lower is flagged when one term holds the demand',
      /80% of demand is .car accident attorney./.test(flag), flag);
  const growFlag = await p.evaluate(() => {
    const r = ROWS[0];
    r.result.pricing.total_volume = 4200; r.result.pricing.vol_free_below = 10000;
    return budgetFlags(r).grow;
  });
  say('higher is flagged under the free volume', /4,200\/mo, under 10,000\/mo/.test(growFlag),
      growFlag);
  const none = await p.evaluate(() => {
    const r = ROWS[0];
    r.kw.service_volume = {a: 5000, b: 5000, c: 5000};
    r.result.pricing = {total_volume: 15000, vol_free_below: 10000,
                        competitive_adder: 1300, competitive_adder_cap: 1300};
    const f = budgetFlags(r);
    r.kw.service_volume = {'car accident attorney': 8000, 'dog bite lawyer': 2000};
    r.result.pricing = {handoff: {package: {base: 13050, intermediate: 15350,
                                            advanced: 17600}}};
    return f;
  });
  say('no flag when the list is not what moves the price',
      none.lower === '' && none.grow === '', none);
  await p.click('[data-variant="lower"][data-row="0"]');
  await p.waitForSelector('[data-variantbox="0"]:not([hidden])', {timeout: 5000});
  const box = await p.textContent('[data-variantbox="0"]');
  say('the list goes with its tiers',
      (variantBody.rows || []).some(x => x.tier === 'ultra'), variantBody);
  say('the run\'s click prices go with it',
      (variantBody.cpc || {})['car accident attorney'] === 180, variantBody.cpc);
  say('priced on the new adder and volume',
      priceBody.adder === 600 && priceBody.total_volume === 8750, priceBody);
  say('the not-ranking share is the run\'s', priceBody.pct_not_ranking === 100, priceBody);
  say('shows the new price beside the old', /\$9,900/.test(box) && /\$13,050/.test(box), box);
  say('names what went out and came in',
      /car accident attorney/.test(box) && /slip and fall lawyer/.test(box), box);

  await p.click('[data-usevariant="0"]');
  await p.waitForTimeout(200);
  const after = await p.evaluate(() => ({
    all: ROWS[0].kw.all.map(x => x.kw), total: ROWS[0].kw.total_volume,
    label: document.getElementById('gen').textContent.trim(),
    open: !document.getElementById('scrim').hidden}));
  say('the variant becomes the list', after.all.includes('slip and fall lawyer seattle')
      && !after.all.includes('car accident attorney seattle'), after.all);
  say('its volume moves with it', after.total === 8750, after.total);
  say('the form opens on Regenerate', after.open && after.label === 'Regenerate Quote', after);
  say('no page errors', errs.length === 0, errs);
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
