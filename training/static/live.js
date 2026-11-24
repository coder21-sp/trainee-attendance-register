const live = document.querySelector('#live');
const download = document.querySelector('#download');
let lastState;
async function update() {
  try {
    const response = await fetch(live.dataset.feed, {cache:'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    const signature = JSON.stringify(data);
    // Review controls are rendered server-side; refresh them if approval or eligibility changes.
    const status = data.rows.map(r => [r.id,r.status].join('/')).join(',');
    if (!download && lastState !== undefined && status !== lastState) {
      location.reload();
      return;
    }
    lastState = status;
    if (signature !== live.dataset.snapshot) {
      showRows('summary', data.rows.map(r => r.name + ' · ' + r.marked + '/' + r.total + ' marked · ' + r.status));
      showRows('counts', data.sessions.map(s => s.title + ' · ' + (s.status ?? (s.count + ' present · ' + (s.closed ? 'Closed' : 'Attendance pending')))));
      live.dataset.snapshot = signature;
    }
    if (download) download.hidden = data.rows[0].status !== 'Approved';
    document.querySelector('#health').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch {
    document.querySelector('#health').textContent = 'Could not refresh. Retrying…';
  }
  setTimeout(update, 2000);
}
function showRows(id, lines) {
  document.getElementById(id).replaceChildren(...lines.map(line => {
    const p = document.createElement('p');
    p.textContent = line;
    return p;
  }));
}
update();
