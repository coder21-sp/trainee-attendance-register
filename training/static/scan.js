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
        document.querySelector('#code').value = code.data;
        document.querySelector('#entry').requestSubmit();
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 180));
    }
    statusLine.textContent = 'Scan timed out. Retry or enter the printed ID.';
  } catch {
    statusLine.textContent = 'Camera unavailable. Enter the printed ID.';
  } finally {
    stream?.getTracks().forEach(track => track.stop());
    video.hidden = true;
    scan.disabled = false;
  }
}
if (window.jsQR && navigator.mediaDevices?.getUserMedia) {
  scan.hidden = false;
  scan.addEventListener('click', scanBadge);
}

const form = document.querySelector('#entry');
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (form.dataset.busy) return;
  form.dataset.busy = 'true';
  try {
    const response = await fetch(form.dataset.api, {
      method: 'POST', body: new FormData(form), headers: {Accept:'application/json'}
    });
    const result = await response.json();
    if (!result.saved) {
      statusLine.textContent = result.message;
      return;
    }
    // Reload the server-rendered roster after the transaction commits.
    sessionStorage.setItem('lastMark', result.message);
    location.reload();
  } catch {
    statusLine.textContent = 'Could not verify the mark. Retry the same ID to check.';
  } finally {
    delete form.dataset.busy;
  }
});
const lastMark = sessionStorage.getItem('lastMark');
if (lastMark) {
  statusLine.textContent = lastMark;
  sessionStorage.removeItem('lastMark');
  document.querySelector('#code').focus();
}
