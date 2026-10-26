const filter = document.querySelector('#node-group-filter');
const search = document.querySelector('#node-directory-search');
const sections = [...document.querySelectorAll('[data-directory-kind]')];
const status = document.querySelector('#node-directory-status');
function applyFilter() {
  let total = 0;
  const needle = search.value.trim().toLocaleLowerCase();
  for (const section of sections) {
    const items = [...section.querySelectorAll('[data-directory-node]')];
    for (const item of items) item.hidden = Boolean((filter.value && item.dataset.home !== filter.value) || (needle && !item.dataset.search.toLocaleLowerCase().includes(needle)));
    const count = items.filter(item => !item.hidden).length;
    section.hidden = !count;
    section.querySelector('.count').textContent = count;
    const link = document.querySelector(`.kind-nav [data-kind="${section.dataset.directoryKind}"]`);
    if (link) { link.hidden = !count; link.querySelector('span').textContent = count; }
    total += count;
  }
  status.textContent = total ? `共 ${total} 个节点` : '没有找到匹配节点，请调整搜索或所属章／集合。';
}
const current = new URL(location.href), requested = current.searchParams.get('group');
if ([...filter.options].some(option => option.value === requested)) filter.value = requested;
search.value = current.searchParams.get('q') || '';
applyFilter();
function update() {
  applyFilter();
  const next = new URL(location.href);
  if (filter.value) next.searchParams.set('group', filter.value); else next.searchParams.delete('group');
  if (search.value.trim()) next.searchParams.set('q', search.value.trim()); else next.searchParams.delete('q');
  history.replaceState(null, '', next.pathname + next.search + next.hash);
}
filter.addEventListener('change', update);
search.addEventListener('input', update);
