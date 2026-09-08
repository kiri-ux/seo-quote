// A WARNING THAT OUTLIVED WHAT IT WAS ABOUT.
//
// "2 areas with no state — US, UK" stayed on screen across two rebuilds of a
// quote whose geo box was empty. renderStateNeeded() reads stores.geo, but the
// only thing that called it was the state <select>; removing the pills it named
// never redrew it. (2026-09-08, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const box = () => document.getElementById('stateNeeded');
    const shown = () => !box().classList.contains('hidden');
    const text = () => (box().textContent || '').replace(/\s+/g, ' ').trim();

    document.getElementById('state').value = '';
    stores.geo = ['US', 'UK'];
    PILL_RENDER.geo();
    R.warnsWhenBare = shown();
    R.namesThem = /US, UK/.test(text());

    stores.geo = [];
    PILL_RENDER.geo();
    R.clearsWhenEmptied = !shown();

    // a tagged city needs no fallback at all
    stores.geo = ['Altoona, PA'];
    PILL_RENDER.geo();
    R.quietWhenTagged = !shown();

    // and a bare city with a fallback state set is answered
    stores.geo = ['Altoona'];
    PILL_RENDER.geo();
    R.warnsBareCity = shown();
    document.getElementById('state').value = 'Pennsylvania';
    PILL_RENDER.geo();
    R.quietOnceFallbackSet = !shown();
    return R;
  });

  let fail = [];
  const check = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? '  ok   ' : '  FAIL ') + label);
    if (!ok) { console.log('         got  ' + JSON.stringify(got) +
                           '\n         want ' + JSON.stringify(want)); fail.push(label); }
  };

  console.log('IT APPEARS WHEN SOMETHING WILL FALL BACK');
  check('bare areas warn', out.warnsWhenBare, true);
  check('and are named', out.namesThem, true);

  console.log('\nAND GOES WHEN THEY DO');
  check('emptying the box clears it', out.clearsWhenEmptied, true);
  check('a tagged city never raised it', out.quietWhenTagged, true);

  console.log('\nA FALLBACK STATE ANSWERS IT');
  check('a bare city warns', out.warnsBareCity, true);
  check('and stops once a state is set', out.quietOnceFallbackSet, true);

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
