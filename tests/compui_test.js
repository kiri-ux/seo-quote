// THE TWO THINGS DRAINIFY NEEDED, ON SCREEN.
//
// A UK company entering the US: the client's own site cannot supply a single US
// term, and the price that came out was the bare anchor with nothing beside it
// saying so. One panel reads the competitors instead; one line carries step 1's
// finding down to step 4 where the number is. (2026-09-04, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    R.fieldExists = !!document.getElementById('comp_in');
    R.buttonExists = !!document.getElementById('compRead');

    // ---- the panel ------------------------------------------------------
    const PAYLOAD = {
      keywords: [
        { term: 'sewer inspection software', volume: 20, competitors: 3,
          position: 3, on: ['ariesindustries.com', 'pipelogix.com', 'sewerai.com'],
          vendor_terms: [] },
        { term: 'pacp software', volume: 90, competitors: 2, position: 2,
          on: ['ariesindustries.com', 'pipelogix.com'], vendor_terms: [] },
        { term: 'pipelogix login', volume: 300, competitors: 1, position: 1,
          on: ['pipelogix.com'], vendor_terms: ['pipelogix'] },
      ],
      domains_read: ['ariesindustries.com', 'pipelogix.com', 'sewerai.com'],
      domains_failed: ['broken.com'], total: 9, shared: 2, already_seeded: 1,
      family_capped: [],
    };
    let asked = null;
    const real = window.fetch;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/competitor_seeds')) {
        asked = JSON.parse(o.body);
        return { ok: true, status: 200, text: async () => JSON.stringify(PAYLOAD),
                 json: async () => PAYLOAD };
      }
      return real(u, o);
    };

    stores.kw = ['drain survey']; stores.geo = [];
    document.getElementById('comp_in').value =
      'https://ariesindustries.com/products/\nwww.pipelogix.com, sewerai.com';
    await runCompetitorSeeds();
    const box = document.getElementById('compKwOut');
    R.text = (box.textContent || '').replace(/\s+/g, ' ').trim();
    R.sent = asked ? asked.competitors : null;
    R.seedsSent = asked ? asked.seeds : null;

    const chips = [...box.querySelectorAll('.svc-chip')];
    R.chipOrder = chips.map(c => c.getAttribute('data-label'));
    R.chipsAreSeedable = chips.every(c => c.getAttribute('data-src') === 'competitor');
    R.sharedCountShown = /2 held by more than one/.test(R.text);
    R.failureNamed = /broken\.com/.test(R.text);
    R.countsOnChip = /3\/3/.test(chips[0].textContent || '');

    // clicking one puts it in Product / Vertical Focus, as the planner's own
    // seed -- which is what exempts it from the competitor-name filter
    const before = stores.kw.slice();
    chips[0].click();
    R.addedOnClick = stores.kw.filter(x => !before.includes(x));
    R.addAllOffered = !!box.querySelector('.svcAddAll');

    // an empty box asks rather than calling
    document.getElementById('comp_in').value = '';
    asked = null;
    await runCompetitorSeeds();
    R.emptyDidNotCall = asked === null;
    R.emptyAsks = /at least one competitor/i.test(
      document.getElementById('compKwOut').textContent || '');
    window.fetch = real;

    // ---- the price warning ----------------------------------------------
    const BASIS = { anchor: 1800, competitive_adder: 50, industry_anchor_add: 0,
                    pageone_anchor_add: 0, volume_add: 0,
                    zero_ranking_uplift_pct: 0, total_volume: 90,
                    manual_base: false };
    R.warned = noDemandHtml({ no_demand: true, price_basis: BASIS });
    R.quiet = noDemandHtml({ no_demand: false, price_basis: BASIS });
    R.quietOnMissing = noDemandHtml({});
    return R;
  });

  let fail = [];
  const check = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? '  ok   ' : '  FAIL ') + label);
    if (!ok) { console.log('         got  ' + JSON.stringify(got) +
                           '\n         want ' + JSON.stringify(want)); fail.push(label); }
  };

  console.log('THE FIELD IS ON THE FORM');
  check('a place to paste them', out.fieldExists, true);
  check('and a button', out.buttonExists, true);

  console.log('\nURLS ARE TAKEN HOWEVER THEY ARE PASTED');
  check('newlines and commas both split',
        out.sent, ['https://ariesindustries.com/products/', 'www.pipelogix.com',
                   'sewerai.com']);
  check('and the current seeds go with them', out.seedsSent, ['drain survey']);

  console.log('\nTHE CATEGORY VOCABULARY COMES FIRST');
  check('ordered as the server ranked them',
        out.chipOrder, ['sewer inspection software', 'pacp software',
                        'pipelogix login']);
  check('every chip is seedable', out.chipsAreSeedable, true);
  check('the overlap is on the chip', out.countsOnChip, true);
  check('and summarised above it', out.sharedCountShown, true);
  check('a competitor that could not be read is named', out.failureNamed, true);

  console.log('\nA CHIP ENTERS AS THE PLANNER\u2019S OWN SEED');
  check('clicking adds it to the focus list',
        out.addedOnClick, ['sewer inspection software']);
  check('and there is an add-all', out.addAllOffered, true);

  console.log('\nAN EMPTY BOX COSTS NOTHING');
  check('no call is made', out.emptyDidNotCall, true);
  check('and it says what it wants', out.emptyAsks, true);

  console.log('\nTHE PRICE SAYS WHEN IT RESTS ON NOTHING');
  check('it fires', /Priced without a demand signal/.test(out.warned), true);
  check('naming the total it judged on', /90\/mo/.test(out.warned), true);
  check('and what was live', /competition/.test(out.warned), true);
  check('and what was not', /at zero: demand volume, current visibility/
        .test(out.warned), true);
  check('it points at the way out', /competitors/.test(out.warned), true);
  check('a measured quote says nothing', out.quiet, '');
  check('and neither does a quote with no pricing yet', out.quietOnMissing, '');

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
