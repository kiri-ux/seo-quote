// The overview cards. A card for a workstream the quote did not buy is noise,
// and a percentage over the wrong denominator is worse than no percentage.
const fs = require('fs');
const s = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
const view = s.slice(s.indexOf('function plannerView'),
                     s.indexOf('function runSettings') > 0
                       ? s.indexOf('function runSettings') : s.length);
// Only the SEO branch -- the ORM quote has its own margin and its own
// "not on this quote" lines, which are correct there.
const body = view.slice(view.indexOf('} else {'));
let bad = 0;
const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

// The three internal tiles are gone from the overview.
for (const gone of ['month term', "add('Margin'", "add('Partner cost'"])
  say('removed:' + gone, !body.includes(gone), 'still present');

// Nothing is added unconditionally for a workstream that is off.
say('noAiPlaceholder', !body.includes("'not on this quote'"), 'AI Search still placeholds');
// Core SEO and AI Search live in the tier tiles now, not their own cards.
say('noCoreCard', !/add\('Core SEO'/.test(body), 'Core SEO card still present');
say('noAiCard', !/add\('AI Search'/.test(body), 'AI Search card still present');
say('splitInTiles', /splitOf = t =>/.test(s) && /\$\{cost \? splitOf\(t\) : ''\}/.test(s));
say('splitGated', /h\.core_seo_sold === false \|\| !h\.ai_search_pct/.test(s));
say('addonGated', /if \(h\.addon_markets\)/.test(body));

// Strategy is its own widget.
say('strategyCard', /add\('Strategy'/.test(body));

// The ranking denominator is the measured count, not the list length.
say('ranking.usesOkChecks', /okChecks/.test(body));
say('ranking.noListDenominator',
    !/\$\{100 - p\.pct_not_ranking\}% of \$\{checked\} terms ranking/.test(body));
say('ranking.namesUnmeasured', /unmeasured/.test(body));

// The exact arithmetic that produced "100% of 12 terms ranking".
const rank = (nTerms, checked, errored, pct) => {
  const okChecks = Math.max(checked - errored, 0);
  const ranking = okChecks - Math.round(okChecks * (pct || 0) / 100);
  return pct == null
    ? 'unmeasured'
    : `${ranking} of ${okChecks} measured term${okChecks === 1 ? '' : 's'} ranking`
      + (okChecks < nTerms ? ` · ${nTerms - okChecks} unmeasured` : '');
};
say('rank.milliganVein', rank(12, 12, 11, 0) === '1 of 1 measured term ranking · 11 unmeasured',
    rank(12, 12, 11, 0));
say('rank.allChecked', rank(12, 12, 0, 25) === '9 of 12 measured terms ranking',
    rank(12, 12, 0, 25));
say('rank.noneRanking', rank(12, 12, 0, 100) === '0 of 12 measured terms ranking',
    rank(12, 12, 0, 100));
say('rank.unmeasured', rank(12, 12, 12, null) === 'unmeasured', rank(12, 12, 12, null));

console.log(bad ? `failed=${bad}` : 'ok=15 failed=0');
process.exit(bad ? 1 : 0);
