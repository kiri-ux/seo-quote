// QUOTE THE CLIENT FOR THE OTHER PRODUCT FROM THE PAGE THAT ALREADY HAS THEM.
// A client with a reputation quote and no SEO quote meant going back to the
// grid, starting a blank quote and retyping the brand, the website, the
// markets, the industry and the order number the quote in front of you already
// carries. (2026-09-18, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  const QUOTE = {id: 5, tool: 'rep', client: 'City Heating and Air', payload: {adtini: {
    kind: 'orm', qid: 'Q-100244', built: '2026-09-17',
    data: {brand: 'City Heating and Air', site: 'cityheatandair.com',
           order_no: '44973', partner: 'Lockwood Digital', markup: '40',
           business_desc: 'HVAC service in Knoxville', industry: ['Home Services'],
           strategy: ['Reactive'], volume: 500, locations: 1,
           g_city: true, city: ['Knoxville, TN'], county: [], state: [], countries: []},
    result: {quote: {lines: [], totals: {monthly: 6350}}, settings: {}}, history: []}}};
  // The catch-all goes on first: Playwright matches the most recently
  // registered route, so a catch-all added last answers everything.
  await p.route('**/api/**', r =>
    r.fulfill({status:200, contentType:'application/json', body:'{}'}));
  await p.route('**/api/adtini/clients', r => r.fulfill({status:200,
    contentType:'application/json', body: JSON.stringify({enabled: true, clients: [
      {client: 'City Heating and Air', order: '44973', planner: 'Kiri',
       partner: 'Lockwood Digital', status: 'Pending', updated: '2026-09-17',
       seo: 0, orm: 1, seoStrat: [], ormStrat: ['Reactive'],
       quotes: [{id: 5, name: 'City Heating', updated_at: '2026-09-17T10:00:00'}]}]})}));
  await p.route('**/api/quotes/5', r => r.fulfill({status:200,
    contentType:'application/json', body: JSON.stringify(QUOTE)}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=City%20Heating%20and%20Air&order=44973',
               {waitUntil:'networkidle'});
  // ROWS is a top-level const, so it is script scope, not a window property.
  await p.waitForFunction(() => typeof ROWS !== 'undefined' && ROWS.length === 1
                                && (ROWS[0].data || {}).brand, null, {timeout:15000});

  // Only the product they do NOT have is offered.
  const buttons = await p.$$eval('[data-add]', ns => ns.map(n => n.textContent.trim()));
  say('offersTheMissingProduct', buttons.join(',') === '+ SEO quote', JSON.stringify(buttons));

  await p.click('[data-add="seo"]');
  await p.waitForTimeout(300);
  const got = await p.evaluate(() => {
    const r = ROWS[ROWS.length - 1];
    return {n: ROWS.length, kind: r.kind, d: r.data, id: r.id, qid: r.qid,
            formOpen: !document.getElementById('scrim').hidden,
            seoForm: !document.getElementById('fseo').hidden};
  });
  say('itIsANewRow', got.n === 2 && got.kind === 'seo', JSON.stringify(got));
  say('theOldQuoteIsStillThere',
      (await p.evaluate(() => ROWS[0].kind)) === 'orm');
  say('andItIsNotSavedOverTheOther', !got.id && !!got.qid, JSON.stringify([got.id, got.qid]));
  say('opensOnItsOwnForm', got.formOpen && got.seoForm);

  // What belongs to the CLIENT rides over.
  say('brand', got.d.brand === 'City Heating and Air', got.d.brand);
  say('website', got.d.site === 'cityheatandair.com', got.d.site);
  say('orderNumber', got.d.order_no === '44973', got.d.order_no);
  say('partner', got.d.partner === 'Lockwood Digital', got.d.partner);
  say('markup', got.d.markup === '40', got.d.markup);
  say('markets', (got.d.city || []).join(',') === 'Knoxville, TN', JSON.stringify(got.d.city));
  say('marketCheckbox', got.d.g_city === true, String(got.d.g_city));
  say('industry', (got.d.industry || []).join(',') === 'Home Services',
      JSON.stringify(got.d.industry));
  say('whatTheClientDoes', got.d.business_desc === 'HVAC service in Knoxville',
      got.d.business_desc);

  // What belongs to the PRODUCT starts empty.
  say('noSeedsCarriedOver', (got.d.focus || []).length === 0, JSON.stringify(got.d.focus));
  say('itsOwnStrategy', (got.d.strategy || []).join(',') === 'Core SEO',
      JSON.stringify(got.d.strategy));

  // And with both products on the client, nothing is offered.
  await p.evaluate(() => draw());
  await p.waitForTimeout(200);
  say('nothingLeftToOffer', (await p.$$('[data-add]')).length === 0);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
