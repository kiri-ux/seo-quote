// THE DOWNLOAD FAILED AND THE PAGE SAID NOTHING.
//
// Errors went to #ppMsg, an element renderProposal() creates -- and a re-price
// redraws that whole tab 450ms after the add-on count moves. A download already
// running then finished against detached nodes: the button it re-enabled was
// not the button on screen and the message landed nowhere. Kiri clicked, waited,
// and got no file and no line. (2026-09-09, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const priced = n => ({
      anchor: 1800, base: 1850, markup_pct: 35, addon_markets: n,
      competitive_adder: 50, min_term_months: 6,
      client_tiers: { base: 2950, intermediate: 4000, advanced: 5100 },
      client_addon_per_market: { base: 2655, intermediate: 3600, advanced: 4590 },
      addon_discount_pct: 10, handoff: { addon_markets: n },
    });
    ST.inputs = { brand: 'Drainify', strategy: 'Core SEO', addon_markets: 1,
                  markup_pct: 35, geo_scope: 'nationwide', geo_values: [] };
    ST.kw = { all: [], ultra: [], competitive: [], long_tail: [] };
    ST.table = []; ST.perfOn = false;
    ST.pricing = priced(1);

    const real = window.fetch;
    const say = () => (document.getElementById('ppMsg') || {}).textContent || '';

    // ---- a server error is reported, not swallowed ----------------------
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/proposal.docx')) {
        return { ok: false, status: 500,
                 json: async () => ({ error: 'python-docx is not installed on this server.' }),
                 headers: { get: () => null } };
      }
      if (String(u).includes('/api/price')) {
        const pay = priced(1);
        return { ok: true, status: 200, text: async () => JSON.stringify(pay),
                 json: async () => pay };
      }
      return real(u, o);
    };
    renderProposal();
    // Clicked, not called — the binding is the thing that broke.
    document.getElementById('ppDownload').click();
    await new Promise(r => setTimeout(r, 200));
    R.errShown = say();
    R.buttonBack = (document.getElementById('ppDownload') || {}).textContent || '';

    // ...and it still works after the tab redraws itself
    renderProposal();
    renderProposal();
    document.getElementById('ppDownload').click();
    await new Promise(r => setTimeout(r, 200));
    R.errAfterRedraws = say();

    // ---- a sleeping instance is retried, not reported --------------------
    let tries = 0;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/proposal.docx')) {
        tries++;
        if (tries < 3) return { ok: false, status: 502, json: async () => ({}),
                                headers: { get: () => null } };
        return { ok: true, status: 200, headers: { get: () => null },
                 blob: async () => new Blob(['x']) };
      }
      return real(u, o);
    };
    renderProposal();
    const t0 = Date.now();
    await downloadProposal();
    R.tries502 = tries;
    R.waited = Date.now() - t0 >= 4000;
    R.recovered = /Downloaded/.test(say());

    // a 500 is NOT retried — the document is what is wrong
    let tries500 = 0;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/proposal.docx')) {
        tries500++;
        return { ok: false, status: 500, json: async () => ({ error: 'bad table' }),
                 headers: { get: () => null } };
      }
      return real(u, o);
    };
    renderProposal();
    await downloadProposal();
    R.tries500 = tries500;

    // ---- a network refusal too -----------------------------------------
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/proposal.docx')) throw new TypeError('Failed to fetch');
      return real(u, o);
    };
    renderProposal();
    await downloadProposal();
    R.netShown = say();

    // ---- a re-render mid-flight must not steal the page ----------------
    let release = null;
    window.fetch = async (u, o) => {
      if (String(u).includes('/api/proposal.docx')) {
        await new Promise(r => { release = r; });
        return { ok: false, status: 500, json: async () => ({ error: 'boom' }),
                 headers: { get: () => null } };
      }
      if (String(u).includes('/api/price')) {
        const pay = priced(2);
        return { ok: true, status: 200, text: async () => JSON.stringify(pay),
                 json: async () => pay };
      }
      return real(u, o);
    };
    renderProposal();
    const btnBefore = document.getElementById('ppDownload');
    const flight = downloadProposal();
    await new Promise(r => setTimeout(r, 50));
    renderProposal();                       // what a re-price does
    R.sameButtonStillThere = document.getElementById('ppDownload') === btnBefore;
    R.stillBuilding = /Building/.test(btnBefore.textContent || '');
    release();
    await flight;
    R.errAfterRace = say();
    R.buttonBackAfterRace = (document.getElementById('ppDownload') || {}).textContent || '';
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

  console.log('A FAILURE IS ALWAYS SAID OUT LOUD');
  check('the server error reaches the screen',
        /python-docx is not installed/.test(out.errShown), true);
  check('and the button comes back', /Download proposal/.test(out.buttonBack), true);
  check('and a redrawn button still works',
        /python-docx is not installed/.test(out.errAfterRedraws), true);
  check('a network refusal too', /Failed to fetch/.test(out.netShown), true);

  console.log('\nA SLEEPING HOST IS WAITED OUT');
  check('502 is retried until it answers', out.tries502, 3);
  check('with a real pause between tries', out.waited, true);
  check('and the file still arrives', out.recovered, true);
  check('a 500 is asked once and reported', out.tries500, 1);

  console.log('\nA RE-RENDER WAITS FOR THE DOWNLOAD');
  check('the button on screen is the one that was clicked',
        out.sameButtonStillThere, true);
  check('and it still says what it is doing', out.stillBuilding, true);
  check('the error still lands when it finishes',
        /boom/.test(out.errAfterRace), true);
  check('and the button is usable again',
        /Download proposal/.test(out.buttonBackAfterRace), true);

  console.log(fail.length ? '\n' + fail.length + ' FAILED: ' + fail.join(', ') : '\nall OK');
  await b.close();
  process.exit(fail.length ? 1 : 0);
})();
