// WEBSITE AUDIT IS NEVER SOLD WITH AI SEARCH. The adtini Strategy picker took
// all three chips, and the quote repriced with them. Picking one now takes the
// other off the list, and a saved quote carrying both opens without the audit.
// (2026-10-26, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify', {waitUntil:'networkidle'});

  const R = await p.evaluate(async () => {
    await listsReady();
    const box = document.querySelector('#fseo [data-chips="strategy"]');
    const opts = () => [...box.querySelectorAll('.pick')].map(x => x.dataset.v);
    const R = {listed: LISTS.strategies};
    chipbox(box, ['Core SEO', 'AI Search']);
    picksDraw(box.querySelector('.chipin'));
    R.withAi = opts();
    chipbox(box, ['Website Audit']);
    picksDraw(box.querySelector('.chipin'));
    R.withAudit = opts();
    chipbox(box, ['AI Search']);
    picksTake(box.querySelector('.chipin'), 'Website Audit');
    R.taken = chipsOf(box);
    load($('fseo'), {strategy: ['Core SEO', 'AI Search', 'Website Audit']});
    R.loaded = chipsOf(document.querySelector('#fseo [data-chips="strategy"]'));
    load($('fseo'), {strategy: ['Core SEO', 'Website Audit']});
    R.loadedAudit = chipsOf(document.querySelector('#fseo [data-chips="strategy"]'));
    return R;
  });
  say('list.hasAudit', (R.listed || []).includes('Website Audit'), JSON.stringify(R.listed));
  say('ai.hidesAudit', !R.withAi.includes('Website Audit'), JSON.stringify(R.withAi));
  say('audit.hidesAi', !R.withAudit.includes('AI Search') && R.withAudit.includes('Core SEO'),
      JSON.stringify(R.withAudit));
  say('take.refused', !R.taken.includes('Website Audit'), JSON.stringify(R.taken));
  say('load.dropsAudit', JSON.stringify(R.loaded) === '["Core SEO","AI Search"]',
      JSON.stringify(R.loaded));
  say('load.keepsAuditAlone', JSON.stringify(R.loadedAudit) === '["Core SEO","Website Audit"]',
      JSON.stringify(R.loadedAudit));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
