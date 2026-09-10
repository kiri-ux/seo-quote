// TWO NUMBERS BEING COMPARED HAVE TO BE ABLE TO DIFFER ON SCREEN.
// "sewer crawler at 4% is below the 4% a guaranteed slot needs" — 3.7 and 4.0
// both rounded to 4. (2026-09-10, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    ST.kw = {
      all: [], head: [], ultra: [], competitive: [], long_tail: [],
      topics: [
        { label: 'drain survey reporting software', share: 70, services: 13 },
        { label: 'sewer crawler', share: 4, services: 1 }],
      topic_fixes: [{ kind: 'unprotected', topic: 'sewer crawler',
                      share: 0.037, needed_share: 0.04, slots: 20 }],
    };
    renderStep1();
    const t = $('p1').textContent || '';
    R.line = (t.match(/sewer crawler at [^ ]+ is below the [^ ]+ a guaranteed/) || [''])[0];
    R.differs = /at 3\.7% is below the 4\.0%/.test(t);
    R.noSelfComparison = !/at 4% is below the 4%/.test(t);

    // Numbers that already differ stay whole.
    ST.kw.topic_fixes = [{ kind: 'unprotected', topic: 'x',
                           share: 0.09, needed_share: 0.20, slots: 10 }];
    renderStep1();
    R.wholeWhenClear = /at 9% is below the 20%/.test($('p1').textContent || '');
    return R;
  });

  const want = { differs: true, noSelfComparison: true, wholeWhenClear: true };
  let bad = 0;
  for (const k of Object.keys(want)) {
    const ok = out[k] === want[k];
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  FAIL ') + k
      + (ok ? '' : `  got ${JSON.stringify(out[k])} want ${JSON.stringify(want[k])}`));
  }
  console.log('  line: ' + out.line);
  await b.close();
  console.log(`\n${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad ? 1 : 0);
})();
