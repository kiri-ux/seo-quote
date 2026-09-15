// THE FORM AS ADTINI DRAWS IT.
//
// A third tab, so the shape can be agreed against a screenshot of the real
// Regenerate Forecast modal before either working tool is touched. Keywords
// are built behind the header button, not in the form. (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.goto('http://127.0.0.1:5199/adtini', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(() => {
    const R = {};
    const css = el => getComputedStyle(el);
    const hex = c => '#' + c.match(/\d+/g).slice(0, 3)
      .map(n => (+n).toString(16).padStart(2, '0')).join('').toUpperCase();

    // the modal chrome
    R.title = document.querySelector('.sheet .top h2').textContent.trim();
    R.headerNavy = hex(css(document.querySelector('.sheet .top')).backgroundColor);
    R.pills = [...document.querySelectorAll('.toppills .pill')]
      .map(x => x.textContent.trim()).filter(Boolean);
    R.footer = [...document.querySelectorAll('.foot .btn')].map(x => x.textContent.trim());
    R.generateOrange = hex(css(document.querySelector('.btn.go')).backgroundColor);
    R.saveBlue = hex(css(document.querySelector('.btn.save')).backgroundColor);

    // two forms, one at a time
    R.tabs = [...document.querySelectorAll('#which button')].map(x => x.textContent.trim());
    R.seoOpenFirst = !document.getElementById('fseo').hidden
                  && document.getElementById('form').hidden;

    const labels = f => [...document.getElementById(f).querySelectorAll('label, .geohead')]
      .map(x => x.childNodes[0].textContent.trim()).filter(Boolean);
    R.seoFields = labels('fseo');

    document.querySelectorAll('#which button')[1].click();
    R.ormOpen = document.getElementById('fseo').hidden
             && !document.getElementById('form').hidden;
    R.ormFields = labels('form');

    // a Yes/No pair moves as one
    document.querySelectorAll('#which button')[0].click();
    const yn = document.querySelector('#fseo .yn');
    yn.querySelectorAll('button')[1].click();
    R.ynMoved = [...yn.querySelectorAll('button')].map(x => x.classList.contains('on'));

    // chips come off with their x
    const box = document.getElementById('s_focus');
    const before = box.querySelectorAll('.chip').length;
    box.querySelector('.chip b').click();
    R.chipRemoved = box.querySelectorAll('.chip').length === before - 1;

    // keywords are built behind the header button
    R.kwBuilderIsHeader = !!document.querySelector('.toppills #kwBuilder');
    R.noKwBuildInForm = !labels('fseo').some(t => /keyword builder|build keyword|generate keyword/i.test(t));
    return R;
  });

  const want = {
    title: 'Regenerate Forecast',
    headerNavy: '#123A63',
    generateOrange: '#E2761B',
    saveBlue: '#1C5BC4',
    pills: ['↻', '✎ Keyword Builder', 'Revert to Default'],
    footer: ["Save But Don't Generate", 'Generate Forecast'],
    tabs: ['SEO', 'Online Reputation Management'],
    seoOpenFirst: true,
    ormOpen: true,
    ynMoved: [false, true],
    chipRemoved: true,
    kwBuilderIsHeader: true,
    noKwBuildInForm: true,
  };
  let bad = 0;
  for (const k of Object.keys(want)) {
    const g = JSON.stringify(out[k]), w = JSON.stringify(want[k]);
    const ok = g === w;
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  FAIL ') + k + (ok ? '' : `  got ${g} want ${w}`));
  }
  // field inventories, printed rather than pinned — they are the thing under review
  console.log('\n  SEO : ' + out.seoFields.join(' · '));
  console.log('\n  ORM : ' + out.ormFields.join(' · '));
  await b.close();
  console.log('\nerrors: ' + (errs.length ? errs.join('; ') : 'none'));
  console.log(`${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad || errs.length ? 1 : 0);
})();
