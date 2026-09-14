// A DOWNLOAD THAT FAILS HAS TO SAY SO, AND SAY WHICH ONE.
//
// Both buttons wrote to one message line, so "Downloaded." from the review
// removal stood while the full proposal had failed -- and the failure itself
// only ever said "Request failed". (2026-09-14, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/reputation', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    const reply = (status, body, ct) => async () => ({
      ok: status < 400, status,
      headers: { get: () => ct },
      text: async () => body,
      blob: async () => new Blob([body]),
    });
    const settle = () => new Promise(r => setTimeout(r, 300));
    lastQuote = { lines: [], totals: {}, handoff: {} };
    window._negDone = [{ title: 'x', profile_rating: 4, profile_reviews: 10,
                         neg_1: 1, neg_2: 0, weak_3: 0 }];

    R.twoMessageLines = !!($('dlMsg') && $('dlMsgRem'));

    // the server's own words survive
    window.fetch = reply(500, JSON.stringify({ error: 'python-docx is not installed' }), 'application/json');
    $('dlRepProposal').click(); await settle();
    R.serverWords = $('dlMsg').textContent;

    // a status with no body still names the status
    window.fetch = reply(413, '', 'text/html');
    $('dlRepProposal').click(); await settle();
    R.bareStatus = $('dlMsg').textContent;

    // a 200 that is not a document is not a download
    window.fetch = reply(200, '<html>Proxy error</html>', 'text/html');
    $('dlRepProposal').click(); await settle();
    R.wrongType = $('dlMsg').textContent.slice(0, 40);

    // an empty document is a failure, not a silent save
    window.fetch = reply(200, '', DOCX);
    $('dlRepProposal').click(); await settle();
    R.empty = $('dlMsg').textContent;

    // success names the size
    window.fetch = reply(200, 'x'.repeat(40000), DOCX);
    $('dlRepProposal').click(); await settle();
    R.ok = $('dlMsg').textContent;

    // and the two buttons no longer speak over each other
    $('dlMsgRem').textContent = 'Downloaded · 38 KB.';
    window.fetch = reply(500, JSON.stringify({ error: 'boom' }), 'application/json');
    $('dlRepProposal').click(); await settle();
    R.remUntouched = $('dlMsgRem').textContent;
    R.proposalFailed = $('dlMsg').textContent;
    return R;
  });

  const want = {
    twoMessageLines: true,
    serverWords: 'HTTP 500 — python-docx is not installed',
    bareStatus: 'HTTP 413',
    wrongType: 'Server sent text/html instead of a docum',
    empty: 'Document came back empty (0 bytes).',
    ok: 'Downloaded · 39 KB.',
    remUntouched: 'Downloaded · 38 KB.',
    proposalFailed: 'HTTP 500 — boom',
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
