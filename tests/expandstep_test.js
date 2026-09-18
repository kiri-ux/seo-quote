// ✦ EXPAND IS A BUTTON AND ↻ REFRESH IS A TOGGLE BESIDE IT. Expand was read by
// Build, so pressing it did nothing you could see and a build you had not asked
// for ran it. Now the button is the whole instruction: press it, the three
// passes run, the proposals land in the seed box marked ✦, and Build builds on
// what is left. Refresh off adds to the list; Refresh on starts the suggestions
// over -- the tool's own ✦ terms come off and the removed ones are offered
// again -- which is what Restore and Allow again used to be.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  const hits = [];
  const list = {all: [{kw: 'hearing aids oxford ms', vol: 20}],
                ultra: [{kw: 'hearing aids oxford ms', vol: 20}], competitive: [], long_tail: []};
  // Their site answers the same whatever is in the box; the gap pass is the one
  // that is told the list, so it is the one asked twice.
  const SITE = {services: [{term: 'ear tube surgery', volume: 40},
                           {term: 'allergy shots', volume: 0},
                           {term: 'earwax removal', volume: 10}], floor: 20};
  let gapCalls = 0;
  await p.route('**/api/**', route => {
    const u = new URL(route.request().url()).pathname;
    hits.push(u);
    if (/expand_services$/.test(u)) gapCalls++;
    // The gap pass has nothing to work from until the first pass has put
    // something on the list -- which is the whole reason it runs twice.
    const gap = gapCalls % 2 === 0
      ? {services: [{term: 'sinus surgery', volume: 90}], floor: 20, proposed: 1, rejected: []}
      : {services: [], floor: 20, proposed: 0, rejected: []};
    const body = /keywords$|refine$/.test(u) ? list
               : /site_services$/.test(u) ? SITE
               : /expand_services$/.test(u) ? gap
               : {};
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout: 15000});
  const seeds = () => p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => ({t: n.firstChild.textContent.trim(), sug: n.classList.contains('sug')})));
  const expand = async () => {
    await p.evaluate(() => { $('saved').textContent = ''; });
    await p.click('#kbExpandRun');
    await p.waitForFunction(
      () => /proposed|added nothing|under the|no |full at/i.test($('saved').textContent),
      null, {timeout: 20000});
  };
  const build = async () => {
    await p.evaluate(() => { $('saved').textContent = ''; });
    await p.click('#kbBuild');
    await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent),
                            null, {timeout: 20000});
  };

  await p.evaluate(() => {
    const r = ROWS[ROW];
    r.data.focus = ['Hearing Aids', 'Tonsillectomy'];
    r.data.site = 'https://www.entoxford.com/';
    r.seedDrop = []; r.seedSrc = {};
    r.suggested = []; r.rankedSeeds = [];
    open(ROW, 'kw');
  });
  await p.waitForTimeout(300);

  // The two controls, in the first two rows under the seeds.
  say('expandIsAButton', await p.$('#kbExpandRun') != null);
  say('noExpandToggle', await p.$('#kbExpand') == null);
  say('refreshIsAToggle', await p.$('#kbRefresh button[data-v="1"]') != null);
  say('refreshDefaultsOff',
      (await p.getAttribute('#kbRefresh button[data-v="0"]', 'class') || '').includes('on'));
  const order = await p.$$eval('#paneKw .kbrow .f label',
    ns => ns.map(n => n.textContent.trim().replace(/\s*i$/, '')));
  say('expandAndRefreshFirst',
      order[0] === '✦ Expand on focus terms' && order[1] === '↻ Refresh focus terms',
      JSON.stringify(order));

  // THE BUTTON RUNS IT, and nothing is built.
  hits.length = 0;
  await expand();
  say('expandCallsTheSources', ['site_services', 'expand_services', 'rank_seeds']
      .every(k => hits.some(u => u.endsWith('/' + k))), hits.join('|'));
  say('expandDoesNotBuild', !hits.some(u => /\/api\/keywords$|\/api\/refine$/.test(u)),
      hits.join('|'));
  say('gapAskedTwice', gapCalls === 2, gapCalls + ' gap calls');
  say('siteAskedOnce', hits.filter(u => /site_services$/.test(u)).length === 1, hits.join('|'));
  let got = await seeds();
  say('measuredProposalIsIn', got.some(x => x.t === 'ear tube surgery' && x.sug), JSON.stringify(got));
  say('secondPassTermIsIn', got.some(x => x.t === 'sinus surgery' && x.sug), JSON.stringify(got));
  say('zeroVolumeIsOut', !got.some(x => x.t === 'allergy shots'), JSON.stringify(got));
  say('underFloorIsOut', !got.some(x => x.t === 'earwax removal'), JSON.stringify(got));
  say('lineSaysProposed', /2 terms proposed, marked ✦/.test(await p.textContent('#saved')),
      await p.textContent('#saved'));

  // BUILD DOES NOT EXPAND.
  hits.length = 0;
  await build();
  say('buildDoesNotExpand',
      !hits.some(u => /site_services|expand_services|rank_seeds/.test(u)), hits.join('|'));
  say('buildLineSaysNothingOfExpansion', !/xpansion/.test(await p.textContent('#saved')));

  // REFRESH OFF: a second press ADDS to the list, it does not replace it.
  hits.length = 0;
  await expand();
  say('secondPressAsksAgain', hits.some(u => /site_services$/.test(u)), hits.join('|'));
  got = await seeds();
  say('suggestionsNotDuplicated',
      got.filter(x => x.t === 'ear tube surgery').length === 1, JSON.stringify(got));

  // REFRESH ON: the tool's own terms come off first, the typed ones stay, and a
  // term the planner removed is offered again.
  await p.evaluate(() => [...document.querySelectorAll('#paneKw [data-chips="seeds"] .chip')]
    .find(c => c.firstChild.textContent.trim() === 'ear tube surgery')
    .querySelector('b').click());
  await p.waitForTimeout(200);
  say('removalRecorded',
      await p.evaluate(() => (ROWS[ROW].seedDrop || []).includes('ear tube surgery')));
  await p.click('#kbRefresh button[data-v="1"]');
  await expand();
  say('refreshStaysOn', await p.evaluate(() => ROWS[ROW].data.refresh) === 1);
  got = await seeds();
  say('typedTermsUntouched',
      ['Hearing Aids', 'Tonsillectomy'].every(t => got.some(x => x.t === t)),
      JSON.stringify(got));
  say('refreshClearsTheBlock',
      (await p.evaluate(() => (ROWS[ROW].seedDrop || []).length)) === 0);
  say('removedTermIsOfferedAgain', got.some(x => x.t === 'ear tube surgery'),
      JSON.stringify(got));
  say('stillNoDuplicates',
      got.filter(x => x.t === 'sinus surgery').length <= 1, JSON.stringify(got));

  // The legend no longer offers Restore / Allow again -- Refresh is the way back.
  say('noRestoreButton', await p.$('#seedRestore') == null);
  say('noAllowAgainButton', await p.$('#seedAllow') == null);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
