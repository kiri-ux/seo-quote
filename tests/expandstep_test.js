// ✦ EXPAND ON FOCUS TERMS IS A TOGGLE, AND ↻ REFRESH FOCUS TERMS IS A CHECKBOX
// -- panel fields 8 and 9 on the forecast sheet. Expand is on by default and
// runs ONCE PER LIST, inside the build and ahead of it; Refresh overrides that
// for one build, takes the tool's own previous suggestions back off the list
// first, and then clears itself. A term the planner typed is never touched.
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
    const gap = gapCalls > 1
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
    r.expandDone = []; r.seedDrop = []; r.seedSrc = {};
    r.suggested = []; r.rankedSeeds = [];
    open(ROW, 'kw');
  });
  await p.waitForTimeout(300);

  // The two fields, as the sheet names them.
  say('expandIsAToggle', await p.$('#kbExpand .yn, #kbExpand') != null
      && await p.$('#kbExpand button[data-v="1"]') != null);
  say('noExpandButton', await p.$('#kbExpandRun') == null);
  say('expandDefaultsOn', (await p.getAttribute('#kbExpand button[data-v="1"]', 'class') || '')
      .includes('on'));
  say('refreshIsACheckbox',
      (await p.getAttribute('#kbRefresh', 'type')) === 'checkbox');
  say('refreshStartsClear', !(await p.isChecked('#kbRefresh')));

  // THE BUILD EXPANDS. Both passes run, the second one only asking the gap.
  hits.length = 0;
  await build();
  say('buildCallsTheSources', ['site_services', 'expand_services', 'rank_seeds']
      .every(k => hits.some(u => u.endsWith('/' + k))), hits.join('|'));
  say('gapAskedTwice', gapCalls === 2, gapCalls + ' gap calls');
  say('siteAskedOnce', hits.filter(u => /site_services$/.test(u)).length === 1, hits.join('|'));
  let got = await seeds();
  say('measuredProposalIsIn', got.some(x => x.t === 'ear tube surgery' && x.sug), JSON.stringify(got));
  say('secondPassTermIsIn', got.some(x => x.t === 'sinus surgery' && x.sug), JSON.stringify(got));
  say('zeroVolumeIsOut', !got.some(x => x.t === 'allergy shots'), JSON.stringify(got));
  say('underFloorIsOut', !got.some(x => x.t === 'earwax removal'), JSON.stringify(got));
  say('buildLineSaysWhatItAdded',
      /2 terms added by expansion/.test(await p.textContent('#saved')),
      await p.textContent('#saved'));

  // ONCE PER LIST. The second build on the same seeds asks nothing.
  hits.length = 0;
  await build();
  say('secondBuildStandsDown',
      !hits.some(u => /site_services|expand_services|rank_seeds/.test(u)), hits.join('|'));

  // ↻ REFRESH. Its own suggestions come off the list first, the typed terms stay.
  hits.length = 0;
  await p.check('#kbRefresh');
  await build();
  say('refreshReExpands', hits.some(u => /site_services$/.test(u)), hits.join('|'));
  say('refreshClearsItself', !(await p.isChecked('#kbRefresh')));
  got = await seeds();
  say('typedTermsUntouched',
      ['Hearing Aids', 'Tonsillectomy'].every(t => got.some(x => x.t === t)),
      JSON.stringify(got));
  say('suggestionsNotDuplicated',
      got.filter(x => x.t === 'ear tube surgery').length === 1, JSON.stringify(got));

  // THE TOGGLE OFF IS THE TOGGLE OFF.
  hits.length = 0;
  await p.evaluate(() => { ROWS[ROW].expandDone = []; });
  await p.click('#kbExpand button[data-v="0"]');
  await build();
  say('offSkipsTheExpansion',
      !hits.some(u => /site_services|expand_services|rank_seeds/.test(u)), hits.join('|'));
  say('offIsRecordedOnTheQuote', (await p.evaluate(() => ROWS[ROW].data.expand)) === 0);

  // Removed on the FORM, it stays removed: the next expansion does not bring
  // it back.
  await p.click('#kbExpand button[data-v="1"]');
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
  await p.check('#kbRefresh');
  await build();
  got = await seeds();
  say('removedNotProposedAgain', !got.some(x => x.t === 'ear tube surgery'), JSON.stringify(got));
  say('legendCountsTheRemoval', /1 removed/.test(await p.textContent('#paneKw .seedhint')),
      await p.textContent('#paneKw .seedhint'));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
