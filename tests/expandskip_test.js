// SKIPPED, AND SAID SO. expandDone rides in the saved payload and the note
// does not, so a reopened quote rebuilt on the same seeds ran no expansion and
// printed nothing about it -- which reads as Expand doing nothing.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  const hits = [];
  const list = {all: [{kw: 'hearing aids oxford ms', vol: 20}],
                ultra: [{kw: 'hearing aids oxford ms', vol: 20}], competitive: [], long_tail: []};
  await p.route('**/api/**', route => {
    const u = new URL(route.request().url()).pathname;
    hits.push(u);
    const body = /keywords$|refine$/.test(u) ? list : {};
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout: 15000});

  // A reopened quote: Expand on, seeds unchanged since the last expansion,
  // four of its proposals removed, and no note in memory.
  await p.evaluate(() => {
    const r = ROWS[ROW];
    r.data.focus = ['Hearing Aids', 'Tonsillectomy'];
    r.data.expand = 1;
    r.data.site = 'https://www.entoxford.com/';
    r.expandDone = ['hearing aids', 'tonsillectomy'];
    r.seedDrop = ['allergy testing', 'ear tube surgery', 'sinus surgery', 'balloon sinuplasty'];
    r.expandNote = null;
    open(ROW, 'kw');
  });
  await p.waitForTimeout(300);
  hits.length = 0;
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent),
                          null, {timeout: 15000});
  const line = await p.textContent('#saved');
  say('saysItWasSkipped', /Expansion already ran on these seeds/.test(line), line);
  say('countsTheRemoved', /4 removed/.test(line), line);
  say('didNotCallTheThreeSources',
      !hits.some(u => /site_services|expand_services|rank_seeds/.test(u)), hits.join('|'));

  // A changed seed list runs it again, and the skip line goes away.
  await p.evaluate(() => { ROWS[ROW].data.focus.push('Nasal Polyp Removal');
    chipbox(document.querySelector('#paneKw [data-chips="seeds"]'), ROWS[ROW].data.focus.slice()); });
  hits.length = 0;
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent),
                          null, {timeout: 15000});
  const line2 = await p.textContent('#saved');
  say('newSeedRunsIt', hits.some(u => /expand_services/.test(u)), hits.join('|'));
  say('skipLineGone', !/already ran/.test(line2), line2);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
