// ORDER ID AND PARTNER BELONG TO THE CLIENT. Typed on the forecast page, shown
// on the workflow page, and the proposal file is named after them.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  const metaPosts = [];
  await p.route('**/api/adtini/client_meta', route => {
    if (route.request().method() === 'POST')
      metaPosts.push(route.request().postDataJSON());
    return route.fulfill({status:200, contentType:'application/json', body:'{"ok":true}'});
  });
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify&order=56310',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});

  // The fields are on both forms.
  say('onTheSeoForm',
      (await p.$$('#fseo [data-k="order_no"]')).length === 1
      && (await p.$$('#fseo [data-k="partner"]')).length === 1);
  say('onTheOrmForm',
      (await p.$$('#form [data-k="order_no"]')).length === 1
      && (await p.$$('#form [data-k="partner"]')).length === 1);

  // Typed values round-trip through collect/load.
  await p.evaluate(() => { open(0, 'form'); });
  await p.waitForTimeout(300);
  await p.fill('#fseo [data-k="order_no"]', '56310');
  await p.fill('#fseo [data-k="partner"]', 'Vici Media');
  const got = await p.evaluate(() => collect(document.getElementById('fseo')));
  say('collectsOrder', got.order_no, '56310');
  say('collectsOrderOk', got.order_no === '56310', JSON.stringify(got.order_no));
  say('collectsPartnerOk', got.partner === 'Vici Media', JSON.stringify(got.partner));

  // THE FILE IS NAMED FOR THE DAY, THE CLIENT AND THE ORDER.
  const names = await p.evaluate(() => {
    const n = new Date();
    const pad = x => String(x).padStart(2, '0');
    const stamp = `${pad(n.getMonth() + 1)}${pad(n.getDate())}${n.getFullYear()}`;
    return {stamp,
            withOrder: proposalFilename('ENT Consultants of North MS', '56310'),
            without: proposalFilename('ENT Consultants of North MS', ''),
            blankClient: proposalFilename('', ''),
            slash: proposalFilename('Roof/Repair Co', '1')};
  });
  say('clientFilenameWithOrder',
      names.withOrder === `${names.stamp}_ENT Consultants of North MS_56310.docx`,
      names.withOrder);
  say('clientFilenameWithout',
      names.without === `${names.stamp}_ENT Consultants of North MS.docx`, names.without);
  say('noInventedOrder', !/_\d+\.docx$/.test(names.without), names.without);
  say('blankClientNamed', names.blankClient === `${names.stamp}_Client.docx`,
      names.blankClient);
  say('noPathSeparator', !names.slash.includes('/'), names.slash);

  // Saving writes them where the workflow page reads them.
  await p.route('**/api/quotes/**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"id":1}'}));
  await p.evaluate(async () => {
    const r = ROWS[0];
    r.data.order_no = '56310';
    r.data.partner = 'Vici Media';
    r.saveId = r.saveId || 1;
    LIVE = true;                       // saving is on for this check
    await persist(r);
  });
  await p.waitForTimeout(400);
  const meta = metaPosts[metaPosts.length - 1] || {};
  say('orderWritten', meta.order_no === '56310', JSON.stringify(meta));
  say('partnerWritten', meta.partner === 'Vici Media', JSON.stringify(meta));

  // ---- the workflow page ----
  await p.goto('http://127.0.0.1:5203/adtini', {waitUntil:'networkidle'});
  await p.waitForSelector('#rows tr', {timeout:15000});
  const heads = await p.$$eval('thead th', ns => ns.map(n => n.textContent.trim()));
  say('orderColumnExists', heads.includes('Order ID'), JSON.stringify(heads));
  say('orderBeforePartner',
      heads.indexOf('Order ID') === heads.indexOf('Partner') - 1, JSON.stringify(heads));
  const ords = await p.$$eval('#rows [data-f="order_no"]', ns => ns.map(n => n.value));
  say('everyRowHasTheCell', ords.length > 0, ords.length + ' cells');
  say('noInventedNumbers', ords.every(v => v === ''), JSON.stringify(ords));

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
