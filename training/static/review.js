const filters = document.querySelector('#review-filters');
const search = document.querySelector('#review-search');
const status = document.querySelector('#review-status');
const results = document.querySelector('#review-results');
const trainees = document.querySelectorAll('[data-review-trainee]');

function filterTrainees() {
  const query = search.value.trim().toLocaleLowerCase();
  const selected = status?.value;
  let matches = 0;
  for (const row of trainees) {
    const matchesSearch = row.dataset.reviewTrainee.toLocaleLowerCase().includes(query);
    const matchesStatus = !selected || row.dataset.reviewStatus === selected;
    row.hidden = !(matchesSearch && matchesStatus);
    if (!row.hidden) matches += 1;
  }
  results.textContent = matches ? `${matches} of ${trainees.length} trainees shown` : 'No trainees match these filters.';
}

filters.hidden = false;
search.addEventListener('input', filterTrainees);
status?.addEventListener('change', filterTrainees);
filterTrainees();
