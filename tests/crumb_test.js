const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  // 1. Client in the URL -> client is the breadcrumb.
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Sage%20Dental&order=56305',
               {waitUntil:'networkidle'});
  let c = (await p.textContent('.crumbs')).replace(/\s+/g,' ').trim();
  let h = (await p.textContent('.pagehead h2')).replace(/\s+/g,' ').trim();
  console.log('crumbs:', JSON.stringify(c));
  console.log('head  :', JSON.stringify(h));
  say('crumb.hasClient', c.includes('Sage Dental'), c);
  say('crumb.noOrderId', !c.includes('56305'), c);
  say('head.noOrderId', !h.includes('56305'), h);
  say('crumb.workflow', c.includes('Workflow Page'), c);

  // 2. New quote -> no client, no invented id.
  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  c = (await p.textContent('.crumbs')).replace(/\s+/g,' ').trim();
  h = (await p.textContent('.pagehead h2')).replace(/\s+/g,' ').trim();
  console.log('new crumbs:', JSON.stringify(c));
  console.log('new head  :', JSON.stringify(h));
  say('new.noId', !/\d{5}/.test(c), c);
  say('new.head', h.includes('New quote'), h);

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
