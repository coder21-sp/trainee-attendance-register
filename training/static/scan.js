const scan = document.querySelector('#scan');
const video = document.querySelector('video');
const statusLine = document.querySelector('#camera');
const form = document.querySelector('#entry');
const codeInput = document.querySelector('#code');
let activeScan;

function updateScanButton() {
  scan.disabled = Boolean(activeScan || form.dataset.busy);
}

function stopTracks(stream) {
  stream?.getTracks().forEach(track => track.stop());
}

function stopScan() {
  if (!activeScan) return;
  stopTracks(activeScan.stream);
  activeScan = undefined;
  video.srcObject = null;
  video.hidden = true;
  updateScanButton();
}

async function scanBadge() {
  if (activeScan || form.dataset.busy) return;
  const attempt = {};
  activeScan = attempt;
  updateScanButton();
  try {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', {willReadFrequently: true});
    attempt.stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}});
    if (activeScan !== attempt) {
      stopTracks(attempt.stream);
      return;
    }
    video.srcObject = attempt.stream;
    video.hidden = false;
    await video.play();
    if (activeScan !== attempt) return;
    statusLine.textContent = 'Point the camera at the trainee badge.';
    const until = Date.now() + 20000;
    while (activeScan === attempt && Date.now() < until) {
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        canvas.width = Math.min(640, video.videoWidth);
        canvas.height = Math.max(1, Math.round(video.videoHeight * canvas.width / video.videoWidth));
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(frame.data, frame.width, frame.height);
        if (code) {
          stopScan();
          await submitMark('scan', code.data);
          return;
        }
      }
      await new Promise(resolve => setTimeout(resolve, 180));
    }
    if (activeScan === attempt) statusLine.textContent = 'Scan timed out. Retry or enter the printed ID.';
  } catch {
    if (activeScan === attempt) statusLine.textContent = 'Camera unavailable. Enter the printed ID.';
  } finally {
    if (activeScan === attempt) stopScan();
  }
}
if (!window.isSecureContext) {
  statusLine.textContent = 'Camera access requires HTTPS. Enter the printed ID.';
} else if (window.jsQR && navigator.mediaDevices?.getUserMedia) {
  scan.hidden = false;
  scan.addEventListener('click', scanBadge);
  window.addEventListener('pagehide', stopScan);
} else {
  statusLine.textContent = 'QR scanning is unavailable. Enter the printed ID.';
}

form.addEventListener('submit', event => {
  event.preventDefault();
  stopScan();
  submitMark('manual', codeInput.value);
});
async function submitMark(source, code) {
  if (form.dataset.busy) return;
  form.dataset.busy = 'true';
  updateScanButton();
  statusLine.textContent = 'Saving attendance…';
  try {
    const data = new FormData(form);
    data.set('source', source);
    data.set('code', code);
    const response = await fetch(form.dataset.api, {
      method: 'POST', body: data, headers: {Accept:'application/json'}
    });
    const result = await response.json();
    if (!result.saved) {
      statusLine.textContent = result.message;
      return;
    }
    statusLine.textContent = result.message;
    codeInput.value = '';
    if (source === 'manual') codeInput.focus();
    await refreshRoster();
  } catch {
    statusLine.textContent = 'Could not verify the mark. Retry the same ID to check.';
  } finally {
    delete form.dataset.busy;
    updateScanButton();
  }
}

async function refreshRoster() {
  try {
    const response = await fetch(document.location.href, {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    const roster = page.querySelector('#present-roster');
    if (!roster) throw new Error();
    document.querySelector('#present-roster').replaceWith(roster);
  } catch {
    statusLine.textContent += ' Refresh the page to see the latest roster.';
  }
}
