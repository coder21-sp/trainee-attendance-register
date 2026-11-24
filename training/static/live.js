const live = document.querySelector('#live');
const privateStatus = live.dataset.privateStatus;
const pollInterval = 5000;
const maxRetryDelay = 60000;
let lastState;
let retryDelay = pollInterval;
let pollTimer;
let polling = false;

async function update() {
  if (document.hidden || polling) return;
  polling = true;
  try {
    const response = await fetch(live.dataset.feed, {cache:'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    const signature = JSON.stringify(data);
    // Review controls are rendered server-side; refresh them if approval or eligibility changes.
    const status = data.rows.map(r => [r.id,r.status].join('/')).join(',');
    if (privateStatus !== undefined ? data.rows[0].status !== privateStatus
        : lastState !== undefined && status !== lastState) {
      location.reload();
      return;
    }
    lastState = status;
    if (signature !== live.dataset.snapshot) {
      if (privateStatus !== undefined) {
        if (!data.recovery_required) refreshProgress(data);
      } else {
        showRows('summary', data.rows.map(r => r.name + ' · ' + r.marked + '/' + r.total + ' marked · ' + r.status));
        showRows('counts', data.sessions.map(s => s.title + ' · ' + (s.count + ' present · ' + (s.closed ? 'Closed' : 'Attendance pending'))));
      }
      live.dataset.snapshot = signature;
    }
    document.querySelector('#health').textContent = 'Updated ' + new Date().toLocaleTimeString();
    retryDelay = pollInterval;
  } catch {
    document.querySelector('#health').textContent = 'Could not refresh. Retrying…';
    retryDelay = Math.min(retryDelay * 2, maxRetryDelay);
  } finally {
    polling = false;
  }
  if (!document.hidden) pollTimer = setTimeout(update, retryDelay);
}
function refreshProgress(data) {
  const row = data.rows[0];
  document.getElementById('confirmed-total').textContent = `${row.attended} of ${row.total} sessions confirmed`;
  const pending = data.sessions.filter(session => !session.closed).length;
  const pendingTotal = document.getElementById('pending-total');
  pendingTotal.hidden = pending === 0;
  pendingTotal.textContent = `${pending} ${pending === 1 ? 'register' : 'registers'} still open`;
  if (data.sessions.length) {
    document.getElementById('counts').replaceChildren(...data.sessions.map(session => {
      const row = document.createElement('div');
      const title = document.createElement('span');
      const status = document.createElement('span');
      row.className = 'row';
      title.textContent = session.title;
      status.textContent = session.status;
      row.append(title, status);
      return row;
    }));
  }
}
function showRows(id, lines) {
  document.getElementById(id).replaceChildren(...lines.map(line => {
    const p = document.createElement('p');
    p.textContent = line;
    return p;
  }));
}
document.addEventListener('visibilitychange', () => {
  clearTimeout(pollTimer);
  if (!document.hidden) update();
});
update();
