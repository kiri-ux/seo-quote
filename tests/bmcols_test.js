// THE PANEL A PRICING DECISION GETS MADE ON.
//
// The back-measure is the only place that says whether the aggregator lever
// fires on a client, and it is about to be run across the book to settle
// whether pageone_aggregator_add moves off the one quote it was fitted on. The
// server has returned the reading since 2026-09-19; the table had no column for
// it, so a run would have looked exactly like a run that found nothing.
//
// Mocks the two back-measure routes and drives the Run button, because the real
// one costs five SERPs a client and answers differently every day.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));

  // Three clients: one aggregator-held, one local, one never measured.
  const ROWS = {
    mpg: {id: 'mpg', name: 'MPG Gummies', client: 'MPG Gummies',
          actual_base: 3950, formula_base: 3700,
          pageone_rank: 1000, pageone_add: 0,
          median_rival_rank: 820, client_rank: 40, client_measured: true, gap: 780,
          pageone_agg_share: 0.82, pageone_agg_domains: ['amazon.com', 'walmart.com'],
          pageone_aggregator_add: 300,
          rivals: [{domain: 'amazon.com'}, {domain: 'walmart.com'}]},
    nob: {id: 'nob', name: 'Nob Hill Dental', client: 'Nob Hill Dental',
          actual_base: 2950, formula_base: 3100,
          pageone_rank: 91, pageone_add: 0,
          median_rival_rank: 91, client_rank: 35, client_measured: true, gap: 56,
          pageone_agg_share: 0.18, pageone_agg_domains: ['yelp.com'],
          pageone_aggregator_add: 0,
          rivals: [{domain: 'salemdental.com'}]},
    // A page one that could not be read at all. Not zero aggregators.
    blind: {id: 'blind', name: 'Ski Barn', client: 'Ski Barn',
            actual_base: 2950, formula_base: 2950,
            pageone_rank: null, pageone_add: 0,
            median_rival_rank: null, client_rank: null, client_measured: false,
            gap: null, pageone_agg_share: null, pageone_agg_domains: [],
            pageone_aggregator_add: 0, rivals: []},
  };

  await p.route('**/api/backmeasure/list', r => r.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({targets: [{id: 'mpg'}, {id: 'nob'}, {id: 'blind'}],
                          skipped: [], terms_each: 5})}));
  await p.route('**/api/backmeasure/one', r => {
    const id = (JSON.parse(r.request().postData() || '{}').id) || '';
    return r.fulfill({status: 200, contentType: 'application/json',
                      body: JSON.stringify(ROWS[id] || {})});
  });

  await p.goto('http://127.0.0.1:5199/', {waitUntil: 'domcontentloaded'});
  const table = await p.evaluate(async () => {
    BM.targets = [{id: 'mpg'}, {id: 'nob'}, {id: 'blind'}];
    BM.skipped = []; BM.terms = 5;
    document.getElementById('bmOut') ||
      document.body.insertAdjacentHTML('beforeend', '<div id="bmOut"></div>');
    await runBackmeasure();
    const R = {};
    const t = document.querySelector('#bmOut table');
    R.headers = [...t.querySelectorAll('th')].map(x => x.textContent.trim());
    R.rows = [...t.querySelectorAll('tr')].slice(1).map(
      tr => [...tr.querySelectorAll('td')].map(x => x.textContent.trim()));
    // Rows are sorted by the price sent, so the share column is read back
    // per row rather than by position.
    R.titles = {};
    [...t.querySelectorAll('tr')].slice(1).forEach(tr => {
      const tds = tr.querySelectorAll('td');
      R.titles[tds[0].textContent.trim()] = tds[5].getAttribute('title') || '';
    });
    R.foot = [...document.querySelectorAll('#bmOut .nf')]
      .map(x => x.textContent).find(x => /Sorted by the price/.test(x)) || '';
    return R;
  });

  // Sorted by the price sent, so Nob Hill and Ski Barn ($2,950) come before MPG.
  const row = name => table.rows.find(r => r[0].startsWith(name)) || [];

  say('cols.shareIsAColumn', table.headers.some(h => /aggregators/i.test(h)),
      table.headers.join(' | '));
  say('cols.dollarsAreAColumn', table.headers.some(h => /page-one\s*comp/i.test(h)),
      table.headers.join(' | '));

  const mpg = row('MPG Gummies');
  say('mpg.shareShown', mpg.includes('82%'), mpg.join(' | '));
  say('mpg.addShown', mpg.some(c => c === '+$300'), mpg.join(' | '));

  const nob = row('Nob Hill');
  say('nob.shareShown', nob.includes('18%'), nob.join(' | '));
  // Under the cut, so it reads as measured-and-nothing rather than as a dollar.
  say('nob.noAdd', !nob.some(c => c === '+$300'), nob.join(' | '));

  // NOT MEASURED IS NOT 0%. A page one that could not be read has to look
  // different from one with no aggregators on it, or the run's own blanks get
  // counted as evidence that the lever does not fire.
  const blind = row('Ski Barn');
  say('blind.notZeroPct', !blind.includes('0%'), blind.join(' | '));
  say('blind.dash', blind.includes('—'), blind.join(' | '));

  const mpgTitle = Object.entries(table.titles)
    .find(([k]) => k.startsWith('MPG Gummies'));
  say('hover.namesTheDomains', /amazon\.com/.test((mpgTitle || [])[1] || ''),
      JSON.stringify(table.titles));
  say('foot.saysWhatPays', /Aggregators hold/.test(table.foot), table.foot.slice(0, 120));
  say('errors.none', errs.length === 0, errs.join(' | '));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
