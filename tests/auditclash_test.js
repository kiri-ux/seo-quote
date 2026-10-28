// WEBSITE AUDIT IS SOLD ALONE, AND AI SEARCH ONLY WITH CORE SEO. The adtini
// Strategy picker offers nothing beside the audit and never the audit beside
// anything; AI Search brings Core SEO with it, and Core SEO off takes AI Search
// too. A saved quote opens under the same rules. (2026-10-28, Kiri; story 3082.
// Replaces the 2026-10-26 audit-vs-AI-Search-only rule.)
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify', {waitUntil:'networkidle'});

  const R = await p.evaluate(async () => {
    await listsReady();
    const box = () => document.querySelector('#fseo [data-chips="strategy"]');
    const opts = () => [...box().querySelectorAll('.pick')].map(x => x.dataset.v);
    const R = {listed: LISTS.strategies};
    chipbox(box(), ['Core SEO']);
    picksDraw(box().querySelector('.chipin'));
    R.withCore = opts();
    chipbox(box(), ['Website Audit']);
    picksDraw(box().querySelector('.chipin'));
    R.withAudit = opts();
    chipbox(box(), ['Core SEO']);
    picksTake(box().querySelector('.chipin'), 'Website Audit');
    R.taken = chipsOf(box());
    chipbox(box(), []);
    picksTake(box().querySelector('.chipin'), 'AI Search');
    R.aiTaken = chipsOf(box());
    // Core SEO's x takes AI Search with it.
    [...box().querySelectorAll('.chip')]
      .find(c => c.firstChild.textContent.trim() === 'Core SEO')
      .querySelector('b').click();
    R.coreOff = chipsOf(box());
    load($('fseo'), {strategy: ['Core SEO', 'AI Search', 'Website Audit']});
    R.loaded = chipsOf(box());
    load($('fseo'), {strategy: ['Core SEO', 'Website Audit']});
    R.loadedCoreAudit = chipsOf(box());
    load($('fseo'), {strategy: ['Website Audit']});
    R.loadedAudit = chipsOf(box());
    load($('fseo'), {strategy: ['AI Search']});
    R.loadedAi = chipsOf(box());
    return R;
  });
  say('list.hasAudit', (R.listed || []).includes('Website Audit'), JSON.stringify(R.listed));
  say('core.hidesAudit', !R.withCore.includes('Website Audit') && R.withCore.includes('AI Search'),
      JSON.stringify(R.withCore));
  say('audit.hidesEverything', R.withAudit.length === 0, JSON.stringify(R.withAudit));
  say('take.refused', JSON.stringify(R.taken) === '["Core SEO"]', JSON.stringify(R.taken));
  say('ai.bringsCore', JSON.stringify(R.aiTaken) === '["Core SEO","AI Search"]',
      JSON.stringify(R.aiTaken));
  say('coreOff.takesAi', JSON.stringify(R.coreOff) === '[]', JSON.stringify(R.coreOff));
  say('load.dropsAudit', JSON.stringify(R.loaded) === '["Core SEO","AI Search"]',
      JSON.stringify(R.loaded));
  say('load.dropsAuditBesideCore', JSON.stringify(R.loadedCoreAudit) === '["Core SEO"]',
      JSON.stringify(R.loadedCoreAudit));
  say('load.keepsAuditAlone', JSON.stringify(R.loadedAudit) === '["Website Audit"]',
      JSON.stringify(R.loadedAudit));
  say('load.addsCoreToAi', JSON.stringify(R.loadedAi) === '["Core SEO","AI Search"]',
      JSON.stringify(R.loadedAi));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
