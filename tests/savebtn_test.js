// "Save But Don't Generate" must WRITE. It used to print "Saved 24 fields" off
// a field count with nothing leaving the browser.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  const wrote = [];
  await p.route('**/api/quotes**', async route => {
    const rq = route.request();
    if (rq.method() === 'POST' || rq.method() === 'PUT') {
      wrote.push({m: rq.method(), body: rq.postDataJSON()});
      return route.fulfill({status:200, contentType:'application/json',
                            body: JSON.stringify({id: 4242})});
    }
    return route.fulfill({status:200, contentType:'application/json',
                          body: JSON.stringify({quotes:[]})});
  });
  await p.route('**/api/quotes/status**', route =>
    route.fulfill({status:200, contentType:'application/json',
                   body: JSON.stringify({enabled:true, detail:''})}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout:15000});
  await p.fill('#fseo [data-k="brand"]', 'Milligan Vein');

  await p.click('#save');
  await p.waitForTimeout(700);

  say('wrote.once', wrote.length === 1, JSON.stringify(wrote.map(w=>w.m)));
  say('wrote.post', (wrote[0]||{}).m === 'POST');
  say('wrote.client', ((wrote[0]||{}).body||{}).client === 'Milligan Vein',
      JSON.stringify((wrote[0]||{}).body||{}).slice(0,120));
  say('wrote.payload', !!(((wrote[0]||{}).body||{}).payload||{}).adtini);

  const msg = await p.textContent('#saved');
  say('says.saved', /Saved to Milligan Vein/.test(msg), msg);
  say('no.fieldcount', !/\d+ fields/.test(msg), msg);

  // A second save UPDATES the same record rather than making another.
  await p.click('#save');
  await p.waitForTimeout(700);
  say('second.is.put', wrote.length === 2 && wrote[1].m === 'PUT',
      JSON.stringify(wrote.map(w=>w.m)));

  // No brand -> it says so instead of claiming a save.
  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout:15000});
  const before = wrote.length;
  await p.click('#save');
  await p.waitForTimeout(600);
  say('nobrand.nowrite', wrote.length === before);
  const m2 = await p.textContent('#saved');
  say('nobrand.says.why', /Not saved/.test(m2) && /brand name/.test(m2), m2);

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
