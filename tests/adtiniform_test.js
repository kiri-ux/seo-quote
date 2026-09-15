// THE TOOL AS ADTINI DRAWS IT.
//
// Three pages: a quote list shaped like the workflow table, a per-client
// forecast page whose product rows each hold one saved quote, and the keyword
// builder on its own page. The form is a working form -- an edit survives a
// close and reopen. (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

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
    R.planners = [...new Set([...document.querySelectorAll('tbody select.who')].map(x => x.value))];
    R.plannerOptions = [...document.querySelectorAll('tbody select.who')][0]
      ? [...document.querySelectorAll('tbody select.who')[0].options].map(o => o.textContent) : [];
    R.statusOptions = [...document.querySelectorAll('tbody select.stat')][0]
      ? [...document.querySelectorAll('tbody select.stat')[0].options].map(o => o.textContent) : [];
    R.partnerEditable = !!document.querySelector('tbody input.cell[data-f="partner"]');
    R.hasCreate = !!document.querySelector('.btn-create');
    R.hasRail = document.querySelectorAll('nav.rail a').length > 0;
    const icons = document.querySelectorAll('tbody tr')[2].querySelectorAll('.rowicons a, .rowicons .off');
    R.icons = [...icons].map(x => x.getAttribute('href') || 'none');
    const skiRow = [...document.querySelectorAll('tbody tr')]
      .find(t => t.textContent.includes('Ski Barn'));
    R.seoOffWhenNoSeo = !!skiRow.querySelector('.rowicons .off');
    // an edit sticks on that client
    const inp = document.querySelector('tbody input.cell[data-f="partner"]');
    inp.value = 'Edited Partner';
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    const sel = document.querySelector('tbody select.stat');
    sel.value = 'Complete';
    sel.dispatchEvent(new Event('change', {bubbles: true}));
    document.getElementById('q').value = 'drain';
    document.getElementById('q').dispatchEvent(new Event('input'));
    document.getElementById('q').value = '';
    document.getElementById('q').dispatchEvent(new Event('input'));
    R.partnerKept = document.querySelector('tbody input.cell[data-f="partner"]').value;
    R.statusKept = document.querySelector('tbody select.stat').value;
    R.strategies = [...document.querySelectorAll('tbody tr')[2].querySelectorAll('.strat')]
      .map(x => x.textContent);
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

  // ---------------- a new quote picks its product first ----------------
  const nq = await p.evaluate(() => {
    const R = {};
    R.closed = document.getElementById('newMenu').hidden;
    document.getElementById('newQ').click();
    R.open = !document.getElementById('newMenu').hidden;
    R.items = [...document.querySelectorAll('#newMenu a')].map(a => a.textContent.trim());
    R.links = [...document.querySelectorAll('#newMenu a')].map(a => a.getAttribute('href'));
    document.body.click();
    R.closesAgain = document.getElementById('newMenu').hidden;
    return R;
  });

  // a blank quote of that product, with the form up
  await p.goto(BASE + '/adtini/forecast?new=1&product=orm', { waitUntil: 'domcontentloaded' });
  const blank = await p.evaluate(() => ({
    rows: document.querySelectorAll('.prod').length,
    heading: document.querySelector('.pagehead h2').textContent.trim(),
    name: document.querySelector('.prod > h4').textContent.replace(/\s+/g, ' ').trim(),
    modalOpen: !document.getElementById('scrim').hidden,
    ormForm: !document.getElementById('form').hidden,
    brandEmpty: document.querySelector('#form [data-k="brand"]').value,
    noResults: !document.querySelector('.qres'),
    history: document.querySelector('[data-pane="history"]').textContent.trim(),
  }));

  // ---------------- forecast rows ----------------
  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });
  const fc = await p.evaluate(() => {
    const R = {};
    R.products = [...document.querySelectorAll('.prod > h4')].map(h => h.textContent.replace(/\s+/g, ' ').trim());
    R.tabs = [...document.querySelectorAll('.prod:first-child .ptabs button')].map(x => x.textContent.trim());
    R.actions = [...document.querySelectorAll('.prod:first-child .prow .btn')].map(x => x.textContent.trim());
    // History is a tab on the row, not a separate page
    document.querySelector('.prod:first-child .ptabs button[data-tab="history"]').click();
    // History is empty until a forecast has run -- adtinirun_test covers the
    // populated table.
    R.historyRows = document.querySelectorAll('.prod:first-child .hist tbody tr').length;
    // a quote that has run always has a row, even one saved elsewhere
    const orm = document.querySelectorAll('.prod')[2];
    orm.querySelector('.ptabs button[data-tab="history"]').click();
    R.ormHistoryEmpty = orm.querySelector('[data-pane="history"]').textContent.trim();
    const seo2 = document.querySelectorAll('.prod')[1];
    seo2.querySelector('.ptabs button[data-tab="history"]').click();
    R.seo2HistoryRows = seo2.querySelectorAll('.hist tbody tr').length;
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
    document.querySelector('#fseo [data-k="markup"]').value = 12;
    const inp = document.querySelector('#fseo [data-chips="focus"] .chipin');
    inp.value = 'sedation dentistry';
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    document.querySelector('#fseo .yn[data-k="past"] button[data-v="1"]').click();
    // City takes Enter, because "Boca Raton, FL" is one value
    const cityIn = document.querySelector('#fseo [data-chips="city"] .chipin');
    cityIn.value = 'Delray Beach, FL';
    cityIn.dispatchEvent(new Event('input', {bubbles: true}));
    R.cityNotSplitOnComma =
      document.querySelectorAll('#fseo [data-chips="city"] .chip').length;
    cityIn.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    R.cityPills = [...document.querySelectorAll('#fseo [data-chips="city"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    // County commits on a comma
    document.querySelector('#fseo [data-k="g_county"]').checked = true;
    document.querySelector('#fseo [data-k="g_county"]')
      .dispatchEvent(new Event('change', {bubbles: true}));
    R.countyShown = !document.querySelector('#fseo [data-geo="g_county"]').hidden;
    const cIn = document.querySelector('#fseo [data-chips="county"] .chipin');
    cIn.value = 'Palm Beach County,';
    cIn.dispatchEvent(new Event('input', {bubbles: true}));
    R.countyPills = [...document.querySelectorAll('#fseo [data-chips="county"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    document.getElementById('save').click();
    R.savedMsg = /^Saved \d+ fields to Search Engine Optimization – 9\/16\/26\./
      .test(document.getElementById('saved').textContent);
    document.getElementById('close').click();
    R.closed = document.getElementById('scrim').hidden;
    document.querySelector('[data-open="0"]').click();
    R.brandKept = document.querySelector('#fseo [data-k="brand"]').value;
    R.markupKept = document.querySelector('#fseo [data-k="markup"]').value;
    R.chipKept = [...document.querySelectorAll('#fseo [data-chips="focus"] .chip')]
      .some(c => c.textContent.includes('sedation dentistry'));
    R.toggleKept = document.querySelector('#fseo .yn[data-k="past"] button.on').dataset.v;
    // a chip comes off again
    document.querySelector('#fseo [data-chips="focus"] .chip b').click();
    R.chipRemoved = document.querySelectorAll('#fseo [data-chips="focus"] .chip').length;
    const indSel = document.querySelector('#fseo [data-chips="industry"] .chipsel');
    R.industryIsAList = !!indSel && indSel.options.length > 100;
    R.stratOptions = [...document.querySelector('#fseo [data-chips="strategy"] .chipsel').options]
      .map(o => o.textContent).slice(1);
    R.goalOptions = [...document.querySelector('#fseo [data-chips="goals"] .chipsel').options].length - 1;
    indSel.value = 'Plumbing';
    indSel.dispatchEvent(new Event('change', {bubbles: true}));
    R.industryPicked = [...document.querySelectorAll('#fseo [data-chips="industry"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    document.getElementById('close').click();
    // an ORM row opens the ORM form
    document.querySelector('[data-open="2"]').click();
    R.opensOrm = document.getElementById('fseo').hidden && !document.getElementById('form').hidden;
    R.ormStrategy = [...document.querySelectorAll('#form [data-chips="strategy"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    return R;
  });

  // ---------------- keyword builder is a pane of the same modal ----------
  const kw = await p.evaluate(() => {
    const R = {};
    document.getElementById('close').click();
    // Preview opens the per-quote config, not the form.
    document.querySelector('[data-open="0"][data-view="cfg"]').click();
    R.previewOpensConfig = !document.getElementById('paneCfg').hidden
      && document.getElementById('paneForm').hidden;
    R.cfgFields = [...document.querySelectorAll('#cfgGrid [data-c]')].map(x => x.dataset.c);
    // adtini Forecast opens the form.
    document.getElementById('close').click();
    document.querySelector('[data-open="0"][data-view="form"]').click();
    R.adtiniOpensForm = !document.getElementById('paneForm').hidden;
    // Keyword Builder swaps the body, it does not navigate.
    const before = location.href;
    document.getElementById('kwBuilder').click();
    R.stayedPut = location.href === before;
    R.kwPane = !document.getElementById('paneKw').hidden
      && document.getElementById('paneForm').hidden;
    // The buckets are empty until Build keyword list runs -- adtinirun_test
    // covers the built list.
    R.builtNote = document.getElementById('kbNote').textContent.trim();
    R.hasBuild = !!document.getElementById('kbBuild');
    R.hasSourceToggle = !!document.getElementById('kbSrc');
    R.builderToggles = ['kbNat', 'kbExpand', 'kbLock'].every(id => !!document.getElementById(id));
    R.formHasNoToggles = !document.querySelector('#fseo .yn[data-k="expand"]')
      && !document.querySelector('#fseo .yn[data-k="lock"]')
      && !document.querySelector('#fseo .yn[data-k="national"]')
      && !document.querySelector('#fseo [data-k="markets"]');
    R.seedsFromRow = [...document.querySelectorAll('#paneKw [data-chips="seeds"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    R.generateBecomesApply = document.getElementById('gen').textContent.trim();
    // applying returns to the form with the seeds carried over
    const inp = document.querySelector('#paneKw [data-chips="seeds"] .chipin');
    inp.value = 'veneers';
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    document.getElementById('gen').click();
    R.backOnForm = !document.getElementById('paneForm').hidden;
    R.focusCarried = [...document.querySelectorAll('#fseo [data-chips="focus"] .chip')]
      .some(c => c.textContent.includes('veneers'));
    return R;
  });

  const want = {
    'home.heading': [home.heading, 'Quotes'],
    'home.cols': [home.cols.join('|'),
      'Planner|Built|Client|Products|Strategies|Partner|Status'],
    'home.rows': [home.rows, 8],
    'home.everyoneIsKiri': [home.planners.join(','), 'Kiri'],
    'home.plannerOptions': [home.plannerOptions.join(','), 'Kiri,Stacy,Hana,Megan,SSG'],
    'home.statusOptions': [home.statusOptions.join(','),
      'Pending,In Progress,Ready for SSG Review,Complete'],
    'home.partnerEditable': [home.partnerEditable, true],
    'home.newQuoteButton': [home.hasCreate, true],
    'new.menuStartsClosed': [nq.closed, true],
    'new.menuOpens': [nq.open, true],
    'new.twoProducts': [nq.items.join(' / '),
      'Search Engine Optimization / Online Reputation Management'],
    'new.linksCarryTheProduct': [nq.links.join(' | '),
      '/adtini/forecast?new=1&product=seo | /adtini/forecast?new=1&product=orm'],
    'new.closesOnOutsideClick': [nq.closesAgain, true],
    'new.oneBlankRow': [blank.rows, 1],
    'new.heading': [blank.heading, 'New quote – Online Reputation Management'],
    'new.rowIsThatProduct': [/^Online Reputation Management/.test(blank.name), true],
    'new.opensOnTheForm': [blank.modalOpen && blank.ormForm, true],
    'new.nothingFilledIn': [blank.brandEmpty, ''],
    'new.noQuoteYet': [blank.noResults, true],
    'new.noRunsYet': [blank.history, 'No runs yet.'],
    'home.leftRail': [home.hasRail, true],
    'home.rowIcons': [home.icons.join(' | '),
      '/adtini/forecast?client=Sage%20Dental&order=56305'
      + ' | /adtini/forecast?client=Sage%20Dental&order=56305&review=seo'
      + ' | /adtini/forecast?client=Sage%20Dental&order=56305&review=orm'],
    'home.iconOffWithoutThatProduct': [home.seoOffWhenNoSeo, true],
    'home.partnerEditSticks': [home.partnerKept, 'Edited Partner'],
    'home.statusEditSticks': [home.statusKept, 'Complete'],
    'home.strategiesPerProduct': [home.strategies.join(','),
      'Core SEO,Review Removals,Site/Article Removals,Reactive,Proactive'],
    'home.bothOnOneRow': [home.bothOnOneRow.join(','), 'SEO,ORM'],
    'home.counted': [home.counted.join(','), 'SEO,ORM3'],
    'home.bothOnly': [home.bothOnly, 2],
    'home.ormOnly': [home.ormOnly, 4],
    'home.searched': [home.searched, 1],
    // every quote carries its own id, and the date beside it
    'fc.products': [fc.products.join(' / '),
      'Search Engine Optimization – Q-100241 9/16/26'
      + ' / Search Engine Optimization – Q-100242 9/12/26'
      + ' / Online Reputation Management – Q-100243 9/16/26'],
    'fc.tabs': [fc.tabs.join(','), 'Details,History'],
    'fc.actions': [fc.actions.join(','), 'Config,adtini Forecast'],
    'fc.historyRows': [fc.historyRows, 2],
    'fc.aRunIsAlwaysARow': [fc.seo2HistoryRows, 1],
    'fc.noRunNoRows': [fc.ormHistoryEmpty, 'No runs yet.'],
    'fc.historyCols': [fc.historyCols.join('|'),
      'Date Forecasted|Generated Response|Type|Error'],
    'fc.detailsHidden': [fc.detailsHidden, true],
    'form.opensSeo': [form.opensSeo, true],
    'form.loaded': [form.loaded, 'Sage Dental'],
    'geo.cityKeepsItsComma': [form.cityNotSplitOnComma, 1],
    'geo.cityPills': [form.cityPills.join(' | '), 'Boca Raton, FL | Delray Beach, FL'],
    'geo.childFollowsItsCheckbox': [form.countyShown, true],
    'geo.countyCommitsOnComma': [form.countyPills.join(','), 'Palm Beach County'],
    'form.savedMsg': [form.savedMsg, true],
    'form.closed': [form.closed, true],
    'form.brandKept': [form.brandKept, 'EDITED'],
    'form.markupKept': [form.markupKept, '12'],
    'form.chipKept': [form.chipKept, true],
    'form.toggleKept': [form.toggleKept, '1'],
    'form.chipRemoved': [form.chipRemoved, 3],
    'lists.industryIsTheRzList': [form.industryIsAList, true],
    'lists.strategyOptions': [form.stratOptions.join(','),
      'Core SEO,Core SEO + AI Search,Website Audit'],
    'lists.goalOptions': [form.goalOptions, 11],
    'lists.pickAddsAChip': [form.industryPicked.join(','), 'Healthcare,Plumbing'],
    'form.opensOrm': [form.opensOrm, true],
    'form.ormStrategy': [form.ormStrategy.join(','),
      'Review Removals,Site/Article Removals,Reactive,Proactive'],
    'preview.opensConfig': [kw.previewOpensConfig, true],
    'preview.cfgFields': [kw.cfgFields.join(','),
      'markup,min_term,addon_markets,ov_core,ov_ai,ov_addon,ov_reason'],
    'adtini.opensForm': [kw.adtiniOpensForm, true],
    'kw.staysInModal': [kw.stayedPut, true],
    'kw.pane': [kw.kwPane, true],
    'kw.savedListShown': [kw.builtNote, '7,700/mo measured · United States'],
    'kw.hasBuild': [kw.hasBuild, true],
    'kw.hasSourceToggle': [kw.hasSourceToggle, true],
    'kw.ownsTheThreeToggles': [kw.builderToggles, true],
    'form.keepsNoneOfThem': [kw.formHasNoToggles, true],
    'kw.seedsFromRow': [kw.seedsFromRow.length > 0, true],
    'kw.applyLabel': [kw.generateBecomesApply, 'Apply to the quote'],
    'kw.backOnForm': [kw.backOnForm, true],
    'kw.focusCarried': [kw.focusCarried, true],
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
