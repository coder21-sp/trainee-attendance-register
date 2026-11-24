const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../training/static/scan.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function pendingResult() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

function loadScanner({
  secure = true, supported = true, ready = false, decodable = true, deferredCamera, deferredMark,
} = {}) {
  const events = new Map();
  const timers = [];
  const posts = [];
  let cameraRequests = 0;
  let stoppedTracks = 0;
  let drawnFrames = 0;
  const stream = {getTracks: () => [{stop: () => stoppedTracks++}]};
  const video = {
    hidden: true, videoWidth: ready ? 640 : 0, videoHeight: ready ? 360 : 0, play: async () => {},
  };
  const scan = {hidden: true, addEventListener: (_, fn) => events.set('scan', fn)};
  const status = {textContent: ''};
  const input = {value: 'MANUAL-ID', focus() {}};
  const form = {
    dataset: {api: '/api/sessions/1/attendance/'},
    addEventListener: (_, fn) => events.set('manual', fn),
  };
  const roster = {replaceWith() {}};
  const elements = {
    '#scan': scan, video, '#camera': status, '#code': input, '#entry': form, '#present-roster': roster,
  };
  const jsQR = () => decodable ? {data: 'scan-id'} : null;
  const window = {jsQR, isSecureContext: secure, addEventListener: (event, fn) => events.set(event, fn)};
  const mediaDevices = supported ? {getUserMedia: async () => {
    cameraRequests++;
    if (deferredCamera) await deferredCamera;
    return stream;
  }} : undefined;

  vm.runInNewContext(script, {
    document: {
      querySelector: selector => elements[selector],
      location: {href: '/sessions/1/'},
      createElement: () => ({
        getContext: () => ({
          drawImage: (_, x, y, width, height) => {
            assert.ok(width > 0 && height > 0, 'camera frame must have nonzero dimensions');
            drawnFrames++;
          },
          getImageData: () => ({data: [], width: 640, height: 360}),
        }),
      }),
    },
    window, navigator: {mediaDevices}, jsQR,
    setTimeout: fn => timers.push(fn),
    FormData: class extends Map {
      constructor() { super(); }
    },
    DOMParser: class {
      parseFromString() { return {querySelector: () => roster}; }
    },
    fetch: async (_, options) => {
      if (options.method === 'POST') {
        posts.push([options.body.get('source'), options.body.get('code')]);
        if (deferredMark) await deferredMark;
      }
      return {ok: true, json: async () => ({saved: true, message: 'Saved'}), text: async () => ''};
    },
  });

  return {
    video, scan, status, posts,
    get cameraRequests() { return cameraRequests; },
    get stoppedTracks() { return stoppedTracks; },
    get drawnFrames() { return drawnFrames; },
    start: () => events.get('scan')(),
    submitManual: () => events.get('manual')({preventDefault() {}}),
    pagehide: () => events.get('pagehide')?.(),
    runNextFrame: () => timers.shift()(),
  };
}

test('scanner waits for a decodable camera frame', async () => {
  const scanner = loadScanner();
  const scanning = scanner.start();
  await settle();
  assert.equal(scanner.drawnFrames, 0);
  assert.equal(scanner.video.hidden, false);
  Object.assign(scanner.video, {videoWidth: 1280, videoHeight: 720});
  scanner.runNextFrame();
  await scanning;
  assert.deepEqual(scanner.posts, [['scan', 'scan-id']]);
  assert.equal(scanner.stoppedTracks, 1);
  assert.equal(scanner.video.hidden, true);
});

test('unavailable camera explains HTTPS or printed ID fallback', () => {
  const insecure = loadScanner({secure: false, supported: false});
  assert.match(insecure.status.textContent, /HTTPS.*printed ID/i);
  assert.equal(insecure.scan.hidden, true);
  const unsupported = loadScanner({supported: false});
  assert.match(unsupported.status.textContent, /unavailable.*printed ID/i);
  assert.equal(unsupported.scan.hidden, true);
});

test('pagehide stops the active stream and prevents submission', async () => {
  const scanner = loadScanner({ready: true, decodable: false});
  const scanning = scanner.start();
  await settle();
  const streamWasActive = scanner.video.srcObject;
  scanner.pagehide();
  assert.ok(streamWasActive);
  assert.equal(scanner.stoppedTracks, 1);
  assert.equal(scanner.video.srcObject, null);
  scanner.runNextFrame();
  await scanning;
  assert.deepEqual(scanner.posts, []);
});

test('pagehide stops a stream granted after navigation', async () => {
  const camera = pendingResult();
  const scanner = loadScanner({ready: true, deferredCamera: camera.promise});
  const scanning = scanner.start();
  scanner.pagehide();
  camera.resolve();
  await scanning;
  assert.equal(scanner.stoppedTracks, 1);
  assert.equal(scanner.drawnFrames, 0);
  assert.equal(scanner.video.srcObject, null);
  assert.deepEqual(scanner.posts, []);
});

test('scanner cannot open until a pending manual mark finishes', async () => {
  const mark = pendingResult();
  const scanner = loadScanner({ready: true, deferredMark: mark.promise});
  scanner.submitManual();
  await settle();
  const scanDisabled = scanner.scan.disabled;
  const scanning = scanner.start();
  await settle();
  mark.resolve();
  await scanning;
  await settle();
  assert.equal(scanDisabled, true);
  assert.equal(scanner.cameraRequests, 0);
  assert.equal(scanner.scan.disabled, false);
  assert.deepEqual(scanner.posts, [['manual', 'MANUAL-ID']]);
});
