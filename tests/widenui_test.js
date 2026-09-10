// THE PANEL THAT SAYS THE LIST IS TOO THIN, AND FIXES IT.
// Off unless the build says so; measures before it suggests; adding a term
// puts it in Product / Vertical Focus, where a rebuild will read it.
// (2026-09-10, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const base = () => ({
      all: [], head: [], ultra: [{ kw: 'drain survey software', vol: 10, src: 'grid' }],
      competitive: [], long_tail: [],
    });

    // A healthy list shows nothing.
    ST.kw = Object.assign(base(), { widen: { show: false, fact: 'x' } });
    ST._widen = null; ST._widenAdded = null;
    renderStep1();
    R.hiddenWhenHealthy = !/Find wider buyer terms/.test($('p1').textContent || '');

    // A thin one states the number and offers.
    ST.kw = Object.assign(base(), { widen: {
      show: true, total: 680, measured: 6, top: 'drain manholes', top_share: 0.868,
      fact: '680/mo across 6 measured terms. drain manholes is 87% of it.' } });
    renderStep1();
    const t1 = $('p1').textContent || '';
    R.statesTheFact = /680\/mo across 6 measured terms\. drain manholes is 87% of it\./.test(t1);
    R.offersButton = !!$('widenBtn');

    // Results carry measured volume, strongest first, and an unmeasured
    // candidate is shown as such rather than as a zero.
    ST._widen = { terms: [
      { kw: 'field service management software', vol: 880 },
      { kw: 'job management software', vol: 480 },
      { kw: 'crew scheduling software', vol: 0 } ],
      measured: 2, added_volume: 1360, basis: 'GB national' };
    renderStep1();
    const t2 = $('p1').textContent || '';
    R.buttonGone = !$('widenBtn');
    R.showsTotals = /2 of 3 measured · 1,360\/mo · GB national/.test(t2);
    R.showsVolume = /880/.test(t2);
    R.unmeasuredSaysSo = /no data/.test(t2);
    R.addLinks = document.querySelectorAll('.widenadd').length;

    // Adding puts the term in the focus store, where a rebuild reads it.
    const before = (stores.kw || []).length;
    document.querySelector('.widenadd').click();
    R.pushedToFocus = (stores.kw || []).some(
      x => String(x).toLowerCase() === 'field service management software');
    R.storeGrew = (stores.kw || []).length === before + 1;
    const t3 = $('p1').textContent || '';
    R.marksAdded = /added/.test(t3);
    R.saysRebuild = /Rebuild the list to price them\./.test(t3);
    R.addLinksLeft = document.querySelectorAll('.widenadd').length;

    // Twice does not duplicate it.
    ST._widenAdded = {};
    renderStep1();
    document.querySelector('.widenadd').click();
    R.noDuplicate = (stores.kw || []).filter(
      x => String(x).toLowerCase() === 'field service management software').length;

    // Nothing back is said, not left blank.
    ST._widen = { terms: [], note: 'No wider terms came back.' };
    renderStep1();
    R.emptySaysSo = /No wider terms came back\./.test($('p1').textContent || '');
    return R;
  });

  const want = {
    hiddenWhenHealthy: true, statesTheFact: true, offersButton: true,
    buttonGone: true, showsTotals: true, showsVolume: true,
    unmeasuredSaysSo: true, addLinks: 3, pushedToFocus: true, storeGrew: true,
    marksAdded: true, saysRebuild: true, addLinksLeft: 2, noDuplicate: 1,
    emptySaysSo: true,
  };
  let bad = 0;
  for (const k of Object.keys(want)) {
    const ok = out[k] === want[k];
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  FAIL ') + k
      + (ok ? '' : `  got ${JSON.stringify(out[k])} want ${JSON.stringify(want[k])}`));
  }
  await b.close();
  console.log(`\n${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad ? 1 : 0);
})();
