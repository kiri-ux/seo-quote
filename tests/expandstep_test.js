// EXPANSION IS ITS OWN STEP, BEFORE THE BUILD. It ran inside Build, so every
// weak proposal cost a 130s build to see and another to remove. And their
// site's proposals were never measured, so at fourteen open slots every line
// of the service menu became a seed.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  const hits = [];
  const list = {all: [{kw: 'hearing aids oxford ms', vol: 20}],
                ultra: [{kw: 'hearing aids oxford ms', vol: 20}], competitive: [], long_tail: []};
  const SITE = {services: [{term: 'ear tube surgery', volume: 40},
                           {term: 'allergy shots', volume: 0},
                           {term: 'earwax removal', volume: 10}], floor: 20};
  await p.route('**/api/**', route => {
    const u = new URL(route.request().url()).pathname;
    hits.push(u);
    const body = /keywords$|refine$/.test(u) ? list
               : /site_services$/.test(u) ? SITE
               : /expand_services$/.test(u) ? {services: [], floor: 20, proposed: 0, rejected: []}
               : {};
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout: 15000});
  const seeds = () => p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => ({t: n.firstChild.textContent.trim(), sug: n.classList.contains('sug')})));

  await p.evaluate(() => {
    const r = ROWS[ROW];
    r.data.focus = ['Hearing Aids', 'Tonsillectomy'];
    r.data.site = 'https://www.entoxford.com/';
    r.expandDone = []; r.seedDrop = []; r.seedSrc = {};
    open(ROW, 'kw');
  });
  await p.waitForTimeout(300);

  // The step is a button, and it reads Expand until it has run on these seeds.
  say('expandIsAButton', await p.$('#kbExpandRun') != null);
  say('noToggle', await p.$('#kbExpand') == null);
  say('readsExpand', (await p.textContent('#kbExpandRun')).trim(), 'Expand');

  // Build does not expand.
  hits.length = 0;
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent),
                          null, {timeout: 15000});
  say('buildDoesNotExpand', !hits.some(u => /site_services|expand_services|rank_seeds/.test(u)), hits.join('|'));
  say('buildLineSaysNothingOfExpansion', !/xpansion/.test(await p.textContent('#saved')));

  // Expand runs the three sources and does NOT build.
  hits.length = 0;
  await p.click('#kbExpandRun');
  await p.waitForFunction(() => /proposed|added nothing/.test(document.getElementById('saved').textContent),
                          null, {timeout: 15000});
  say('expandCallsTheSources', ['site_services', 'expand_services', 'rank_seeds']
      .every(k => hits.some(u => u.endsWith('/' + k))), hits.join('|'));
  say('expandDoesNotBuild', !hits.some(u => /\/api\/keywords$|\/api\/refine$/.test(u)), hits.join('|'));
  let got = await seeds();
  say('measuredProposalIsIn', got.some(x => x.t === 'ear tube surgery' && x.sug), JSON.stringify(got));
  say('zeroVolumeIsOut', !got.some(x => x.t === 'allergy shots'), JSON.stringify(got));
  say('underFloorIsOut', !got.some(x => x.t === 'earwax removal'), JSON.stringify(got));
  say('lineSaysProposed', /1 term proposed, shown dashed/.test(await p.textContent('#saved')),
      await p.textContent('#saved'));
  say('nowReadsExpandAgain', (await p.textContent('#kbExpandRun')).trim(), 'Expand again');
  const fi = await p.evaluate(() => ROWS[ROW].expandNote.floorInfo);
  say('floorCounted', fi.rejected === 2 && fi.proposed === 3, JSON.stringify(fi));

  // Removed on the FORM, it stays removed: the next expansion does not bring
  // it back.
  await p.click('#back');
  await p.waitForTimeout(200);
  await p.evaluate(() => {
    const chip = [...document.querySelectorAll('#fseo [data-chips="focus"] .chip')]
      .find(c => c.firstChild.textContent.trim() === 'ear tube surgery');
    chip.querySelector('b').click();
  });
  say('formRemovalRecorded', await p.evaluate(() => (ROWS[ROW].seedDrop || []).includes('ear tube surgery')));
  await p.click('#kwBuilder');
  await p.waitForTimeout(200);
  await p.click('#kbExpandRun');
  await p.waitForFunction(() => /proposed|added nothing|under the/.test(document.getElementById('saved').textContent),
                          null, {timeout: 15000});
  got = await seeds();
  say('removedNotProposedAgain', !got.some(x => x.t === 'ear tube surgery'), JSON.stringify(got));
  say('legendCountsTheRemoval', /1 removed/.test(await p.textContent('#paneKw .seedhint')),
      await p.textContent('#paneKw .seedhint'));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
