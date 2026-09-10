// WHERE THE TERM CAME FROM, ON THE TERM.
//
// A UK build put fifty-one dictionary words in the pool. Every row already
// knew which call had produced it; nothing showed it. The tag is off by
// default and one click away. (2026-09-10, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    ST.kwSrc = false;
    ST.kw = {
      all: [], head: [],
      ultra: [{ kw: 'cctv drain survey software', vol: 90, src: 'ideas' }],
      competitive: [{ kw: 'vict', vol: 301000, src: 'site' },
                    { kw: 'modus operandi', vol: 12100, src: 'suggest' }],
      long_tail: [{ kw: 'how much does a drain survey cost', vol: 0, src: 'gen' },
                  { kw: 'orphan term', vol: 0 }],
    };
    ST.kw.all = [...ST.kw.ultra, ...ST.kw.competitive, ...ST.kw.long_tail];

    renderStep1();
    R.offByDefault = !/\[ideas\]|\[site\]/.test($('p1').textContent || '');
    R.togglePresent = !!$('kwSrcTog');
    R.toggleReads = ($('kwSrcTog').textContent || '').trim();

    $('kwSrcTog').click();
    const t = $('p1').textContent || '';
    R.onAfterClick = ST.kwSrc;
    R.ideas = /\[ideas\]/.test(t);
    R.site = /\[site\]/.test(t);
    R.suggested = /\[suggested\]/.test(t);
    R.generated = /\[generated\]/.test(t);
    R.untagged = /\[\?\]/.test(t);
    R.toggleNowReads = ($('kwSrcTog').textContent || '').trim();

    // The tag rides beside the term, not in place of the volume.
    R.volumeStillThere = /301,000/.test(t);

    // A term typed in by hand names itself.
    const inp = document.querySelector('.kwadd[data-bucket="long_tail"]');
    inp.value = 'drain manholes';
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    R.typedRowTagged = (ST.kw.long_tail.find(r => r.kw === 'drain manholes') || {}).src;
    R.typedShows = /\[typed\]/.test($('p1').textContent || '');

    // Off again.
    $('kwSrcTog').click();
    R.offAgain = !/\[ideas\]/.test($('p1').textContent || '');
    return R;
  });

  const want = {
    offByDefault: true, togglePresent: true, toggleReads: 'sources',
    onAfterClick: true, ideas: true, site: true, suggested: true,
    generated: true, untagged: true, toggleNowReads: 'hide sources',
    volumeStillThere: true, typedRowTagged: 'typed', typedShows: true,
    offAgain: true,
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
