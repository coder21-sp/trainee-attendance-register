const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../training/static/live.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function loadPolling(outcomes = []) {
  const live = {dataset: {feed: '/api/batches/1/'}};
  const health = {};
  const elements = {replaceChildren() {}};
  const timers = new Map();
  const listeners = new Map();
  let requests = 0;
  const document = {
    hidden: false,
    querySelector: selector => selector === '#live' ? live : health,
    getElementById: () => elements,
    createElement: () => ({}),
    addEventListener: (name, callback) => listeners.set(name, callback),
  };

  vm.runInNewContext(script, {
    document,
    fetch: async () => {
      const ok = outcomes[requests++] ?? true;
      return {ok, json: async () => ({rows: [], sessions: []})};
    },
    setTimeout: (callback, delay) => {
      const token = Symbol();
      timers.set(token, {callback, delay});
      return token;
    },
    clearTimeout: token => timers.delete(token),
  });

  return {
    get requests() { return requests; },
    get scheduledDelays() { return Array.from(timers.values(), timer => timer.delay); },
    async runNextPoll() {
      const [token, timer] = timers.entries().next().value;
      timers.delete(token);
      timer.callback();
      await settle();
    },
    async setHidden(hidden) {
      document.hidden = hidden;
      listeners.get('visibilitychange')?.();
      await settle();
    },
  };
}

test('live attendance polls every five seconds while active', async () => {
  const polling = loadPolling();
  await settle();
  assert.equal(polling.requests, 1);
  assert.deepEqual(polling.scheduledDelays, [5000]);
  await polling.runNextPoll();
  assert.equal(polling.requests, 2);
  assert.deepEqual(polling.scheduledDelays, [5000]);
});

test('polling backs off to a one minute cap and resets after success', async () => {
  const polling = loadPolling([false, false, false, false, false, true]);
  await settle();
  for (const expected of [10000, 20000, 40000, 60000, 60000]) {
    assert.deepEqual(polling.scheduledDelays, [expected]);
    await polling.runNextPoll();
  }
  assert.equal(polling.requests, 6);
  assert.deepEqual(polling.scheduledDelays, [5000]);
});

test('polling pauses for hidden tabs and resumes when visible', async () => {
  const polling = loadPolling();
  await settle();
  await polling.setHidden(true);
  assert.deepEqual(polling.scheduledDelays, []);
  assert.equal(polling.requests, 1);
  await polling.setHidden(false);
  assert.equal(polling.requests, 2);
  assert.deepEqual(polling.scheduledDelays, [5000]);
});
