// TWO QUOTES ON ONE PRODUCT, AND NO WAY TO DROP ONE.
//
// A client can carry two reputation forecasts built a day apart -- Q-100244 and
// Q-100245 on the same page. The page could ADD a product row and never remove
// one, so a superseded quote stayed on the client's page for good. The delete
// route has existed since the legacy page; the workflow page had no handle for
// it.
//
// Also here: a measured zero is a measurement. The Search Volume field was
// written only when the total was truthy, so a brand the scan had read and
// found no demand for left the box BLANK -- "0/mo brand volume" on the panel
// next to an empty field, with no telling a measured zero from an unasked
// question.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

  let deleted = [];
  await p.route('**/api/quotes/**', route => {
    const req = route.request();
    if (req.method() === 'DELETE') {
      deleted.push(new URL(req.url()).pathname.split('/').pop());
      return json(route, {ok: true});
    }
    return route.continue();
  });
  p.on('dialog', d => d.accept());

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod');

  // Two rows on the page, one of them saved, the way her client's page reads.
  const before = await p.evaluate(() => {
    while (ROWS.length > 1) ROWS.pop();
    ROWS[0].qid = 'Q-100244'; ROWS[0].saveId = 4244;
    addProductRow('orm');
    ROWS[ROWS.length - 1].qid = 'Q-100245';
    ROWS[ROWS.length - 1].saveId = null;
    ROW = null;
    close();                       // addProductRow opens the modal over the cards
    draw();
    return {rows: ROWS.length,
            buttons: document.querySelectorAll('.prod h4 .rmq').length,
            qids: ROWS.map(r => r.qid)};
  });
  say('bothQuotesAreOnThePage', before.rows === 2, JSON.stringify(before));
  say('andEachHasItsOwnRemove', before.buttons === 2, JSON.stringify(before));

  // Removing the SAVED one deletes the record and drops the card.
  await p.click('.prod[data-row="0"] h4 .rmq');
  await p.waitForFunction(() => ROWS.length === 1);
  const after = await p.evaluate(() => ({
    qids: ROWS.map(r => r.qid),
    cards: document.querySelectorAll('.prod').length,
    // WITH ONE LEFT THERE IS NOTHING TO SEPARATE, and removing it would empty
    // the page with no way back -- the add buttons key off an existing row.
    buttons: document.querySelectorAll('.prod h4 .rmq').length,
  }));
  say('theRightQuoteWasRemoved',
      after.qids.length === 1 && after.qids[0] === 'Q-100245', JSON.stringify(after));
  say('theCardIsGone', after.cards === 1, JSON.stringify(after));
  say('theSavedRecordWentWithIt',
      deleted.length === 1 && deleted[0] === '4244', JSON.stringify(deleted));
  say('theLastQuoteCarriesNoRemove', after.buttons === 0, JSON.stringify(after));

  // AN UNSAVED ROW IS DROPPED FROM THE PAGE ALONE -- no request for a record
  // that was never written.
  deleted = [];
  await p.evaluate(() => {
    addProductRow('seo');
    ROWS[ROWS.length - 1].saveId = null;
    ROWS[ROWS.length - 1].id = '';
    ROW = null;
    close();
    draw();
  });
  await p.click('.prod[data-row="1"] h4 .rmq');
  await p.waitForFunction(() => ROWS.length === 1);
  say('anUnsavedRowCallsNothing', deleted.length === 0, JSON.stringify(deleted));

  // ---------------------------------------------- the measured zero
  const vol = await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'orm';
    const d = r.data = r.data || {};
    // What the scan came back with: it ran, and it read nothing.
    r.scan = {terms: {terms: [], total_volume: 0, negative_volume: 0,
                      watch_volume: 0}};
    const sc = r.scan;
    const v = (sc.terms || {}).total_volume
      || ((sc.terms || {}).terms || []).reduce((z, x) => z + (x.volume || 0), 0);
    if (sc.terms && !sc.terms.error) d.volume = v;
    return d.volume;
  });
  say('aMeasuredZeroReachesTheField', vol === 0, JSON.stringify(vol));

  const stale = await p.evaluate(() => {
    const r = ROWS[0];
    r.data.volume = 4200;            // typed by hand
    const sc = r.scan = {};          // the scan failed, so terms never arrived
    const v = (sc.terms || {}).total_volume
      || ((sc.terms || {}).terms || []).reduce((z, x) => z + (x.volume || 0), 0);
    if (sc.terms && !sc.terms.error) r.data.volume = v;
    return r.data.volume;
  });
  say('aFailedScanLeavesATypedFigureAlone', stale === 4200, JSON.stringify(stale));

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
