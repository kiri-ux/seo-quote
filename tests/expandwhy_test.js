// EXPANSION THAT ADDS NOTHING HAS TO SAY WHY. "Built 10 terms." with Expand on
// reads as the toggle having been ignored. It ran; which pass came back empty
// is the part the planner can act on.
const fs = require('fs');
const s = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
let bad = 0;
const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

const src = s.slice(s.indexOf('function expandWhy(note){'));
const fn = new Function('return ' + src.slice(0, src.indexOf('\n}') + 2))();

say('added', fn({added: ['a', 'b'], found: {}, fails: {}})
    === ' · 2 terms added by expansion.', fn({added: ['a','b'], found:{}, fails:{}}));

// Everything came back empty: name all three.
let t = fn({added: [], found: {site: 0, industry: 0, ranks: 0}, fails: {}});
say('allEmpty.saysNothingAdded', /added nothing/.test(t), t);
say('allEmpty.namesSite', /their site/.test(t), t);
say('allEmpty.namesIndustry', /the industry/.test(t), t);
say('allEmpty.namesRanks', /what they rank for/.test(t), t);

// One pass failed, the others were simply empty: they read differently.
t = fn({added: [], found: {site: 0, industry: 0, ranks: 0}, fails: {site: 'timeout'}});
say('failed.saysUnreadable', /could not be read/.test(t), t);
say('failed.separatesThem', /returned none/.test(t) && /could not be read/.test(t), t);
say('failed.namesTheRightOne', /their site could not be read/.test(t), t);

// It proposed things, all already on the list.
t = fn({added: [], found: {site: 5, industry: 2, ranks: 0}, fails: {}, dupes: true});
say('dupes.saysSo', /already/.test(t), t);

// No expansion at all is silent.
say('off.silent', fn(null) === '', JSON.stringify(fn(null)));

// And the build line uses it.
say('buildLineUsesIt', /Built \$\{\(r\.kw\.all \|\| \[\]\)\.length\} terms\.`\s*\+ expandWhy/.test(s),
    'the build message still hardcodes the expansion clause');
// The per-pass counts are actually collected.
say('countsCollected', /const found = \{site:/.test(s));
say('failuresCollected', /fails\[key\] =/.test(s));

console.log(bad ? 'failed=' + bad : 'ok=13 failed=0');
process.exit(bad ? 1 : 0);
