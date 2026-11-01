// Preserve table columns inside horizontally scrollable, keyboard-accessible regions.
document.querySelectorAll('.site-page table').forEach(table => {
  if (!table.parentElement.classList.contains('ops-panel')) {
    const region = document.createElement('div');
    region.className = 'table-scroll';
    table.before(region);
    region.append(table);
  }
  const region = table.parentElement;
  region.tabIndex = 0;
  region.setAttribute('role', 'region');
  region.setAttribute('aria-label', 'Tableau de données, défilement horizontal disponible');
});
const title = document.querySelector('.site-page h1');
if (title) document.title = `${title.textContent.trim()} — ProfileFinder`;
