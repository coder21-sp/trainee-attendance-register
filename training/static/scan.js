const scan = document.querySelector('#scan');
const video = document.querySelector('video');
const statusLine = document.querySelector('#camera');
let stream;

async function scanBadge() {
  scan.disabled = true;
  try {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', {willReadFrequently:true});
    stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}});
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
    statusLine.textContent = 'Point the camera at the trainee badge.';
    const until = Date.now() + 20000;
    while (Date.now() < until) {
      canvas.width = Math.min(640,video.videoWidth);
      canvas.height = Math.round(video.videoHeight*canvas.width/video.videoWidth);
      ctx.drawImage(video,0,0,canvas.width,canvas.height);
      const frame = ctx.getImageData(0,0,canvas.width,canvas.height);
      const code = jsQR(frame.data,frame.width,frame.height);
      if (code) {
        await submitMark('scan', code.data);
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 180));
    }
    statusLine.textContent = 'Scan timed out. Retry or enter the printed ID.';
  } catch {
    statusLine.textContent = 'Camera unavailable. Enter the printed ID.';
  } finally {
    stream?.getTracks().forEach(track => track.stop());
    video.srcObject = null;
    video.hidden = true;
    scan.disabled = false;
  }
}
if (window.jsQR && navigator.mediaDevices?.getUserMedia) {
  scan.hidden = false;
  scan.addEventListener('click', scanBadge);
}

const form = document.querySelector('#entry');
const codeInput = document.querySelector('#code');
form.addEventListener('submit', async event => {
  event.preventDefault();
  submitMark('manual', codeInput.value);
});
async function submitMark(source, code) {
  if (form.dataset.busy) return;
  form.dataset.busy = 'true';
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
