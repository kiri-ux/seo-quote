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

// THE FLOOR IS THE USUAL ANSWER IN A THIN MARKET, and it is a number the
// planner can change rather than a dead end.
t = fn({added: [], found: {site: 0, industry: 0, ranks: 0}, fails: {},
        floorInfo: {proposed: 18, rejected: 18, floor: 20, thin: true, typical: 10}});
say('floor.countsProposed', /proposed 18 service lines/.test(t), t);
say('floor.countsDropped', /18 measured under the 20\/mo floor/.test(t), t);
say('floor.namesTheMarket', /this market runs about 10\/mo/.test(t), t);
say('floor.saysWhatToDo', /Config/.test(t), t);
say('floor.notBlamingTheIndustryPass', !/the industry returned none/.test(t), t);

// One proposal reads as one.
t = fn({added: [], found: {}, fails: {},
        floorInfo: {proposed: 1, rejected: 1, floor: 20, typical: 0}});
say('floor.singular', /proposed 1 service line;/.test(t), t);

// A missing input is named rather than blamed on the pass.
t = fn({added: [], found: {site: 0, industry: 0, ranks: 0}, fails: {},
        floorInfo: {proposed: 0, rejected: 0, missing: ['Industry', 'Business description']}});
say('missing.named', /no industry or business description to go on/.test(t), t);

// No expansion at all is silent.
say('off.silent', fn(null) === '', JSON.stringify(fn(null)));

// And the build line uses it.
say('buildLineUsesIt', /Built \$\{\(r\.kw\.all \|\| \[\]\)\.length\} terms\.`\s*\+ expandWhy/.test(s),
    'the build message still hardcodes the expansion clause');
// The per-pass counts are actually collected.
say('countsCollected', /const found = \{site:/.test(s));
say('failuresCollected', /fails\[key\] =/.test(s));

console.log(bad ? 'failed=' + bad : 'ok=20 failed=0');
process.exit(bad ? 1 : 0);
