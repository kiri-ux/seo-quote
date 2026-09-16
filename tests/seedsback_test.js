// SEEDS FROM THE LIST, WHEN THE PAYLOAD KEPT NONE. Older saves have an empty
// inputs.keywords, so the Keyword Builder opened on a blank Seed terms box for
// a quote that plainly had a keyword list.
const fs = require('fs');
const s = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
let bad = 0;
const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

// Pull the helper out and run it against a payload shaped like a real one.
const src = s.slice(s.indexOf('const seedsFromList = () =>'),
                    s.indexOf('return out.slice(0, 20);')
                    + 'return out.slice(0, 20);'.length) + '\n  };';
const make = (geo, state, kw) => new Function('geo', 'i', 'pay', 'kwAll',
  src + '\nreturn seedsFromList();')(geo, {state}, {kw}, (kw || {}).all || []);

const GEO = ['Whidbey Island, WA', 'Anacortes, WA', 'Fidalgo Island, WA'];
const ALL = [
  {kw: 'electrical services whidbey island wa'},
  {kw: 'electrical services anacortes wa'},
  {kw: 'electrical services fidalgo island wa'},
  {kw: 'generator installation whidbey island wa'},
  {kw: 'generator installation anacortes wa'},
  {kw: 'kohler generator services fidalgo island wa'},
];
const got = make(GEO, 'WA', {all: ALL});
say('strippedTheMarkets', !got.some(t => /whidbey|anacortes|fidalgo/.test(t)), got.join('|'));
say('strippedTheState', !got.some(t => /\bwa$/.test(t)), got.join('|'));
say('deduped', new Set(got).size === got.length, got.join('|'));
say('keptTheServices',
    got.includes('electrical services') && got.includes('generator installation')
    && got.includes('kohler generator services'), got.join('|'));
say('threeNotSix', got.length === 3, got.join('|'));

// head is preferred when the payload has it.
const h = make(GEO, 'WA', {all: ALL, head: [{kw: 'panel upgrade anacortes wa'}]});
say('prefersHead', h.join('|') === 'panel upgrade', h.join('|'));

// Nothing to work with is an empty list, not a crash.
say('emptyIsEmpty', make([], '', {}).length === 0);
say('noGeoStillTrims', make([], 'WA', {all: [{kw: 'roof repair wa'}]})[0] === 'roof repair',
    JSON.stringify(make([], 'WA', {all: [{kw: 'roof repair wa'}]})));

// The planner's own list always wins over the reconstruction.
say('inputsWin', /i\.keywords \|\| \[\]\)\.length \? \(i\.keywords/.test(s),
    'the saved seeds are no longer preferred');
// And a quote with none says where they come from.
say('emptyBoxExplains', /None on this quote/.test(s));

console.log(bad ? 'failed=' + bad : 'ok=10 failed=0');
process.exit(bad ? 1 : 0);
