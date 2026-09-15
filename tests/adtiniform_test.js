// THE TOOL AS ADTINI DRAWS IT.
//
// Three pages: a quote list shaped like the workflow table, a per-client
// forecast page whose product rows each hold one saved quote, and the keyword
// builder on its own page. The form is a working form -- an edit survives a
// close and reopen. (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5201';

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));

  // ---------------- quote list ----------------
  await p.goto(BASE + '/adtini', { waitUntil: 'domcontentloaded' });
  const home = await p.evaluate(() => {
    const R = {};
    R.heading = document.querySelector('.pagehead h2').textContent.trim();
    R.cols = [...document.querySelectorAll('thead th')].map(t => t.textContent.trim()).filter(Boolean);
    R.rows = document.querySelectorAll('tbody tr').length;
    // a client with both products is ONE row carrying both chips
    const sage = [...document.querySelectorAll('tbody tr')]
      .find(r => r.textContent.includes('Sage Dental'));
    R.bothOnOneRow = [...sage.querySelectorAll('.tag')].map(t => t.textContent.trim());
    // the superscript is how many separate saved quotes that product has
    const jbg = [...document.querySelectorAll('tbody tr')]
      .find(r => r.textContent.includes('Junk Bee Gone'));
    R.counted = [...jbg.querySelectorAll('.tag')].map(t => t.textContent.trim());
    // filters
    document.querySelector('#seg button[data-f="both"]').click();
    R.bothOnly = document.querySelectorAll('tbody tr').length;
    document.querySelector('#seg button[data-f="orm"]').click();
    R.ormOnly = document.querySelectorAll('tbody tr').length;
    document.querySelector('#seg button[data-f="all"]').click();
    document.getElementById('q').value = 'drain';
    document.getElementById('q').dispatchEvent(new Event('input'));
    R.searched = document.querySelectorAll('tbody tr').length;
    return R;
  });

  // ---------------- forecast rows ----------------
  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });
  const fc = await p.evaluate(() => {
    const R = {};
    R.products = [...document.querySelectorAll('.prod > h4')].map(h => h.textContent.replace(/\s+/g, ' ').trim());
    R.tabs = [...document.querySelectorAll('.prod:first-child .ptabs button')].map(x => x.textContent.trim());
    R.actions = [...document.querySelectorAll('.prod:first-child .prow .btn')].map(x => x.textContent.trim());
    // History is a tab on the row, not a separate page
    document.querySelector('.prod:first-child .ptabs button[data-tab="history"]').click();
    R.historyCols = [...document.querySelectorAll('.prod:first-child .hist thead th')]
      .map(t => t.textContent.trim()).filter(Boolean);
    R.detailsHidden = document.querySelector('.prod:first-child [data-pane="details"]').hidden;
    return R;
  });

  // ---------------- the form actually works ----------------
  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });
  await p.click('[data-open="0"]');
  const form = await p.evaluate(() => {
    const R = {};
    R.opensSeo = !document.getElementById('fseo').hidden && document.getElementById('form').hidden;
    R.loaded = document.querySelector('#fseo [data-k="brand"]').value;
    document.querySelector('#fseo [data-k="brand"]').value = 'EDITED';
    document.querySelector('#fseo [data-k="markets"]').value = 12;
    const inp = document.querySelector('#fseo [data-chips="focus"] .chipin');
    inp.value = 'sedation dentistry';
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    document.querySelector('#fseo .yn[data-k="lock"] button[data-v="1"]').click();
    document.getElementById('save').click();
    R.savedMsg = /^Saved \d+ fields to Search Engine Optimization – 137027\.$/
      .test(document.getElementById('saved').textContent);
    document.getElementById('close').click();
    R.closed = document.getElementById('scrim').hidden;
    document.querySelector('[data-open="0"]').click();
    R.brandKept = document.querySelector('#fseo [data-k="brand"]').value;
    R.marketsKept = document.querySelector('#fseo [data-k="markets"]').value;
    R.chipKept = [...document.querySelectorAll('#fseo [data-chips="focus"] .chip')]
      .some(c => c.textContent.includes('sedation dentistry'));
    R.toggleKept = document.querySelector('#fseo .yn[data-k="lock"] button.on').dataset.v;
    // a chip comes off again
    document.querySelector('#fseo [data-chips="focus"] .chip b').click();
    R.chipRemoved = document.querySelectorAll('#fseo [data-chips="focus"] .chip').length;
    document.getElementById('close').click();
    // an ORM row opens the ORM form
    document.querySelector('[data-open="2"]').click();
    R.opensOrm = document.getElementById('fseo').hidden && !document.getElementById('form').hidden;
    R.ormStrategy = [...document.querySelectorAll('#form [data-chips="strategy"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    return R;
  });

  // ---------------- keyword builder is its own page ----------------
  // Clicked from inside the modal, it NAVIGATES, the way Category Mixer does.
  await p.evaluate(() => {
    document.getElementById('close').click();
    document.querySelector('[data-open="0"]').click();
  });
  await Promise.all([
    p.waitForURL(/\/adtini\/keywords/, { timeout: 5000 }),
    p.click('#kwBuilder'),
  ]);
  const kwHref = new URL(p.url()).pathname + new URL(p.url()).search;
  await p.goto(BASE + '/adtini/keywords?row=137027', { waitUntil: 'domcontentloaded' });
  const kw = await p.evaluate(() => ({
    heading: document.querySelector('.pagehead h2').textContent.trim(),
    buckets: [...document.querySelectorAll('.col h5')].map(h => h.childNodes[0].textContent.trim()),
    hasSourceToggle: !!document.getElementById('showSrc'),
    backToForecast: !!document.querySelector('a.back[href="/adtini/forecast"]'),
  }));

  const want = {
    'home.heading': [home.heading, 'Quotes'],
    'home.cols': [home.cols.join('|'),
      'Planner|Built|Client|Order|Products|Partner|Country|Quotes|Status'],
    'home.rows': [home.rows, 8],
    'home.bothOnOneRow': [home.bothOnOneRow.join(','), 'SEO,ORM'],
    'home.counted': [home.counted.join(','), 'SEO,ORM3'],
    'home.bothOnly': [home.bothOnly, 2],
    'home.ormOnly': [home.ormOnly, 4],
    'home.searched': [home.searched, 1],
    'fc.products': [fc.products.map(t => t.replace(/\s*\S$/, '')).join(' / '),
      'Search Engine Optimization – 137027 / Search Engine Optimization – 137031 / Online Reputation Management – 137028'],
    'fc.tabs': [fc.tabs.join(','), 'Details,History'],
    'fc.actions': [fc.actions.join(','), 'Preview,Gemini Forecast,Claude Forecast,adtini Forecast'],
    'fc.historyCols': [fc.historyCols.join('|'),
      'Date Forecasted|Forecast Prompt|Generated Response|Type|Error'],
    'fc.detailsHidden': [fc.detailsHidden, true],
    'form.opensSeo': [form.opensSeo, true],
    'form.loaded': [form.loaded, 'Sage Dental'],
    'form.savedMsg': [form.savedMsg, true],
    'form.closed': [form.closed, true],
    'form.brandKept': [form.brandKept, 'EDITED'],
    'form.marketsKept': [form.marketsKept, '12'],
    'form.chipKept': [form.chipKept, true],
    'form.toggleKept': [form.toggleKept, '1'],
    'form.chipRemoved': [form.chipRemoved, 3],
    'form.opensOrm': [form.opensOrm, true],
    'form.ormStrategy': [form.ormStrategy.join(','),
      'Review Removals,Site/Article Removals,Reactive,Proactive'],
    'kw.opensOwnPage': [kwHref, '/adtini/keywords?row=137027'],
    'kw.heading': [kw.heading, 'Keyword Builder'],
    'kw.buckets': [kw.buckets.join(','), 'Ultra Competitive,Competitive,Long Tail'],
    'kw.hasSourceToggle': [kw.hasSourceToggle, true],
    'kw.backToForecast': [kw.backToForecast, true],
  };
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
