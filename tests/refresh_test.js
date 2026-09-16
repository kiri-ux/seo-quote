// A SAVED QUOTE OUTLIVES THE PAGE. The URL still said ?new=1 after the save, so
// a refresh threw the quote away and opened a blank form.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.route('**/api/quotes**', r => {
    const rq = r.request();
    if (rq.method() === 'POST') return r.fulfill({status:200,
      contentType:'application/json', body: JSON.stringify({id: 77})});
    if (rq.method() === 'PUT') return r.fulfill({status:200,
      contentType:'application/json', body: '{}'});
    return r.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({quotes:[]})});
  });

  await p.route('**/api/quotes/status**', r => r.fulfill({status:200,
    contentType:'application/json', body: JSON.stringify({enabled:true, detail:''})}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout:15000});
  say('starts.new', /[?&]new=1/.test(p.url()), p.url());

  await p.fill('#fseo [data-k="brand"]', 'Whidbey Island Electric');
  await p.click('#save');
  await p.waitForTimeout(700);

  const u = new URL(p.url());
  say('new.dropped', !u.searchParams.has('new'), p.url());
  say('product.dropped', !u.searchParams.has('product'), p.url());
  say('client.set', u.searchParams.get('client') === 'Whidbey Island Electric', p.url());
  say('path.kept', u.pathname === '/adtini/forecast', u.pathname);

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
