// A NATIONAL CAMPAIGN LEFT ON "SINGLE CITY".
//
// Drainify has no geographic areas and is priced on national demand. The server
// answered "nationwide, high confidence" on every build. The dropdown sat on
// Single city for four rebuilds because the no-areas branch of the market
// summary returned before autoApplyScope ran -- the one case its own comment
// says to keep asking about was the one case that never applied the answer.
// (2026-09-08, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const NATIONWIDE = {
      entered: 0, cities: 0, markets: 0, groups: [], unlocated: [],
      non_place: [], state_geos: [], foreign: [], overlaps: [], covered: [],
      scope_suggestion: { suggested: 'nationwide', confidence: 'high',
                          reason: 'Priced on national demand.', evidence: {} },
    };
    const real = window.fetch;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/markets')) {
        return { ok: true, status: 200, text: async () => JSON.stringify(NATIONWIDE),
                 json: async () => NATIONWIDE };
      }
      return real(u, o);
    };

    const sel = document.getElementById('geo_scope');
    sel.value = 'single_city';
    stores.geo = [];
    ST._scopeTouched = false;
    if (document.getElementById('natdemand'))
      document.getElementById('natdemand').checked = true;

    await refreshMarketSummary();
    R.band = sel.value;
    R.derivedText = (document.getElementById('scopeDerived').textContent || '')
      .replace(/\s+/g, ' ').trim();

    // ...but a human who set it keeps it
    sel.value = 'statewide';
    ST._scopeTouched = true;
    await refreshMarketSummary();
    R.bandAfterHumanSet = sel.value;
    R.saysWhoSetIt = /set by you/.test(
      document.getElementById('scopeDerived').textContent || '');
    window.fetch = real;
    return R;
  });

  let fail = [];
  const check = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? '  ok   ' : '  FAIL ') + label);
    if (!ok) { console.log('         got  ' + JSON.stringify(got) +
                           '\n         want ' + JSON.stringify(want)); fail.push(label); }
  };

  console.log('NO AREAS, NATIONAL DEMAND — THE BAND IS STILL SET');
  check('the dropdown follows the derivation', out.band, 'nationwide');
  check('and the line under it says so',
        /Geo scope: Nationwide/i.test(out.derivedText), true);

  console.log('\nAND A HUMAN STILL OUTRANKS IT');
  check('a band set by hand is left alone', out.bandAfterHumanSet, 'statewide');
  check('and is marked as theirs', out.saysWhoSetIt, true);

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
