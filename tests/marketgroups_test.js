// HOW THE MARKETS ARE GROUPED, ON THE MAIN MARKET CARD: the towns that ride
// with the main market, then the add-ons. (2026-10-02, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';
(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  await p.route('**/api/**', route => route.fulfill({status: 200,
    contentType: 'application/json', body: '{}'}));
  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod[data-row="0"] .qres');
  const card = async () => p.evaluate(() => {
    draw();
    return [...document.querySelectorAll('.prod[data-row="0"] .pv')]
      .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent)
      .filter(c => /^(Main market|Add-on markets)/.test(c)).join(' | ');
  });
  const sub = async () => p.evaluate(() => {
    const el = document.querySelector('.prod[data-row="0"] .pvaddon .pvsub');
    return el ? el.textContent : '';
  });
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'seo';
    r.data = Object.assign({}, r.data, {g_city: true,
      city: ['Ardmore, OK', 'Antlers, OK', 'Denison, TX', 'Sherman, TX', 'Paris, TX']});
    r.kw = {all: [{kw: 'dentist sherman tx', city: 'Sherman, TX'}], grid_cities: ['Sherman, TX']};
    r.result = {pricing: {handoff: {package: {base: 3350}, addon_markets: 2,
                                    addon_market_price: {base: 3015}}},
      priceReq: {addon_markets: 2},
      addon: {suggested: 2, markets_absent: ['Antlers, OK', 'Paris, TX']}};
    r.history = [{when: 'now', resp: 'x', quote: r.result, kw: r.kw}];
    r.openRun = 0; r.startTab = 'history';
  });
  const c = await card();
  say('main, its towns, then the add-ons',
      c === 'Main market: Sherman, TX | Add-on markets: Antlers, OK, Paris, TX', c);
  say('the towns with it, under it', await sub() === 'With: Ardmore, Denison', await sub());
  await p.evaluate(() => { ROWS[0].result.addon.basis =
    'contiguous region — 2 over 60 miles from Sherman, TX: a, b.'; });
  await card();
  say('named by the reach', await sub() === 'Within 60 mi: Ardmore, Denison', await sub());
  say('no page errors', errs.length === 0, JSON.stringify(errs));
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
