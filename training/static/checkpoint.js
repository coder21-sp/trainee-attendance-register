const form = document.querySelector('#checkpoint');
const statusText = document.querySelector('#integrity');
const download = document.querySelector('#save-receipt');
const upload = document.querySelector('#verify-receipt');
let latest;
async function verify(file) {
  download.disabled = upload.disabled = true;
  try {
    const key = 'training.audit.receipt.v1';
    const saved = localStorage.getItem(key);
    const candidates = [saved || ''];
    if (file) {
      if (file.size > 2048) throw Error('Invalid receipt file.');
      const token = (await file.text()).trim();
      if (!token) throw Error('Empty receipt file.');
      candidates.push(token);
    }
    let result;
    for (const receipt of candidates) {
      const data = new FormData(form);
      data.set('receipt', receipt);
      const response = await fetch(form.dataset.url, {method:'POST', body:data});
      result = await response.json();
      if (!response.ok) throw Error(result.error || 'Verification failed.');
    }
    latest = result.receipt;
    localStorage.setItem(key, latest);
    statusText.textContent = (saved || file ? 'Saved history verified. ' : 'First receipt saved on this browser. ') + result.count + ' audit entries covered.';
    download.disabled = false;
  } catch (error) {
    statusText.textContent = 'Audit check incomplete: ' + error.message;
  } finally {
    upload.disabled = false;
  }
}
download.onclick = () => {
  const url = URL.createObjectURL(new Blob([latest], {type:'text/plain'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'audit-receipt-' + new Date().toISOString().replaceAll(':','-') + '.txt';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
upload.onchange = () => { if (upload.files.length) verify(upload.files[0]); };
verify();
