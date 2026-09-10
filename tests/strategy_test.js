// STRATEGY IS FOUR WORKSTREAMS, NOT THREE EXCLUSIVE CARDS.
//
// One of the three ("Reactive + Proactive") existed only to name a combination,
// and the exclusivity meant a quote could not carry a review removal beside a
// Brand Shield at all. (2026-09-10, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:5199/reputation', { waitUntil: 'domcontentloaded' });

  const out = await p.evaluate(async () => {
    const R = {};
    const card = k => document.querySelector('.ctype[data-c="' + k + '"]');
    const on = () => [...document.querySelectorAll('.ctype.on')].map(x => x.dataset.c);

    R.cards = [...document.querySelectorAll('.ctype')].map(x => x.dataset.c);
    R.noBundleCard = !card('bundle');
    R.startsOn = on();

    // Multi-select: adding does not clear what is already on.
    card('proactive').click();
    R.twoOn = on();
    R.campaignDerived = campaign;
    card('sites').click();
    R.threeOn = on().length;

    // A removal beside a Brand Shield — the case the old control could not make.
    R.reviewsAndShield = STRAT.has('reviews') && STRAT.has('proactive');
    R.bothSectionsShown = !$('secReactive').classList.contains('hidden')
                       && !$('secProactive').classList.contains('hidden');

    // Cards drive the per-line switches.
    R.useArticlesFollowed = $('useArticles').checked;
    card('sites').click();
    R.useArticlesUnfollowed = $('useArticles').checked;

    // And the per-line switches drive the cards back.
    $('useSearchBundle').checked = true;
    $('useSearchBundle').dispatchEvent(new Event('change'));
    R.searchCardOn = STRAT.has('reactive');

    // The last one cannot be turned off.
    ['proactive', 'reactive'].forEach(k => { if (STRAT.has(k)) card(k).click(); });
    while (STRAT.size > 1) card([...STRAT][1]).click();
    const only = [...STRAT][0];
    card(only).click();
    R.lastStaysOn = STRAT.has(only) && STRAT.size === 1;

    // campaign still derives, for saved quotes and the quote name.
    STRAT.clear(); STRAT.add('reviews'); syncVisibility();
    R.campReactive = campaign;
    STRAT.clear(); STRAT.add('proactive'); syncVisibility();
    R.campProactive = campaign;
    STRAT.add('reviews'); syncVisibility();
    R.campBundle = campaign;

    // Round trip.
    STRAT.clear(); ['reviews', 'sites', 'proactive'].forEach(k => STRAT.add(k));
    paintStrategy(); syncVisibility();
    const saved = collectForm();
    R.saved = saved.strategy;
    STRAT.clear(); STRAT.add('reactive'); paintStrategy(); syncVisibility();
    restoreForm(saved);
    R.restored = [...STRAT].sort().join(',');

    // A quote saved before the four cards existed carries only campaign.
    restoreForm({ campaign: 'bundle', useReviews: true, useArticles: false,
                  useSearchBundle: true });
    R.legacyBundle = [...STRAT].sort().join(',');
    restoreForm({ campaign: 'proactive' });
    R.legacyProactive = [...STRAT].sort().join(',');
    return R;
  });

  const want = {
    cards: ['reviews', 'sites', 'reactive', 'proactive'],
    noBundleCard: true,
    startsOn: ['reviews'],
    twoOn: ['reviews', 'proactive'],
    campaignDerived: 'bundle',
    threeOn: 3,
    reviewsAndShield: true,
    bothSectionsShown: true,
    useArticlesFollowed: true,
    useArticlesUnfollowed: false,
    searchCardOn: true,
    lastStaysOn: true,
    campReactive: 'reactive',
    campProactive: 'proactive',
    campBundle: 'bundle',
    saved: ['reviews', 'sites', 'proactive'],
    restored: 'proactive,reviews,sites',
    legacyBundle: 'proactive,reactive,reviews',
    legacyProactive: 'proactive',
  };
  let bad = 0;
  for (const k of Object.keys(want)) {
    const g = JSON.stringify(out[k]), w = JSON.stringify(want[k]);
    const ok = g === w;
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  FAIL ') + k + (ok ? '' : `  got ${g} want ${w}`));
  }
  await b.close();
  console.log(`\n${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad ? 1 : 0);
})();
