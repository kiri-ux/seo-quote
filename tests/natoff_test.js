// A PLANNER'S NO ON NATIONAL DEMAND STICKS. "Online Sales" as a goal made the
// build answer national_demand, and the page flipped the switch back to Yes on
// every build. The goal sets the starting value; a pick wins. (2026-10-13, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";
const KW = {
  head: [{ kw: 'couches', vol: 6600 }],
  ultra: [{ kw: 'couches', vol: 6600, src: 'seed' }],
  competitive: [], long_tail: [],
  all: [{ kw: 'couches', vol: 6600 }], total_volume: 6600,
  national_demand: true, national_demand_reason: 'goal: Online Sales',
};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  const errs = [], calls = [];
  p.on('pageerror', e => errs.push(e.message));
  const json = (route, body) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    let body = {};
    try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    calls.push({ url, body });
    if (url === '/api/keywords') return json(route, KW);
    if (url === '/api/refine')
      return json(route, Object.assign({}, KW, {national_demand: !body.national_off}));
    return json(route, {});
  });
  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });
  await p.waitForSelector('.prod[data-row="0"]');
  await p.evaluate(() => { ROWS.forEach(r => { delete r.result; delete r.kw;
    delete r.data.nat_pick; r.data.national = 0; }); draw(); });
  await p.click('[data-open="0"][data-view="form"]');
  await p.click('#kwBuilder');
  const nat = () => p.evaluate(() => document.querySelector('#kbNat button.on').dataset.v);
  const build = async () => {
    await p.evaluate(() => { document.getElementById('saved').textContent = ''; });
    await p.click('#kbBuild');
    await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent));
  };
  const lastRefine = () => calls.filter(c => c.url === '/api/refine').slice(-1)[0].body;

  const want = {};
  // Untouched: the build's answer sets the starting value.
  await build();
  want['untouched.flipsOn'] = [await nat(), '1'];
  want['untouched.noOff'] = [lastRefine().national_off, false];
  // The planner says No, and it survives two builds.
  await p.click('#kbNat button[data-v="0"]');
  await build();
  want['no.stays'] = [await nat(), '0'];
  want['no.sentOff'] = [lastRefine().national_off, true];
  want['no.notNationwide'] = [lastRefine().geo_scope !== 'nationwide', true];
  await build();
  want['no.staysAgain'] = [await nat(), '0'];
  // Yes is still Yes.
  await p.click('#kbNat button[data-v="1"]');
  await build();
  want['yes.stays'] = [await nat(), '1'];
  want['yes.noOff'] = [lastRefine().national_off, false];

  let bad = 0;
  for (const k of Object.keys(want)) {
    const [got, exp] = want[k];
    const ok = JSON.stringify(got) === JSON.stringify(exp);
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  FAIL ') + k
      + (ok ? '' : `  got ${JSON.stringify(got)} want ${JSON.stringify(exp)}`));
  }
  await b.close();
  console.log('\nerrors: ' + (errs.length ? errs.join('; ') : 'none'));
  console.log(`${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad || errs.length ? 1 : 0);
})();
