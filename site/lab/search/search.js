const $ = selector => document.querySelector(selector);
const session = window.SearchSession;
let offset = 0;
let historyTicket = 0;
let historyLoading = false;
let historyStarted = false;
let albumTicket = null;
let pageActive = true;
const historyItems = new Map();
const labels = {queued: '等待识别', recognizing: '识别中', pending: '识别中', running: '处理中', generating: '生成中',
  reviewed: '题目已核对', needs_confirmation: '待确认',
  ready: '可开始学习', completed: '可开始学习', failed: '处理失败', error: '处理失败',
  unsupported: '暂不支持', interrupted: '已中断', expired: '已到期', disabled: '已下线', unavailable: '课程不可用',
  unclear: '待确认', figure: '缺少配图'};

function renderMath(root) {
  window.renderMathInElement?.(root, {delimiters: [{left: '$', right: '$', display: false}], throwOnError: false});
}

function toast(text) {
  const element = $('#sq-toast');
  element.textContent = text; element.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { element.hidden = true; }, 2600);
}

function resetHistory() {
  historyTicket++;
  offset = 0;
  historyLoading = false;
  historyStarted = false;
  historyItems.clear();
  $('#sq-history-list').replaceChildren();
  $('#sq-history-list').hidden = !session.user;
  $('#sq-history-guest').hidden = Boolean(session.user);
  $('#sq-history-all').hidden = true;
  $('#sq-history-message').textContent = '';
}

function historyRow(item) {
  const row = document.createElement('li');
  const link = document.createElement('a');
  link.href = 'problem.html?search=' + encodeURIComponent(item.search_id);
  const title = document.createElement('span');
  title.className = 'sq-history-q';
  title.textContent = item.summary || '正在识别题目';
  const meta = document.createElement('span');
  meta.className = 'sq-history-meta';
  meta.textContent = new Date(item.last_searched_at).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'});
  const status = document.createElement('span');
  status.className = 'sq-status';
  const latestStatus = !item.lesson_available && ['ready', 'completed'].includes(item.latest_status) ? 'unavailable' : item.latest_status;
  const latest = labels[latestStatus] || '待处理';
  status.textContent = item.lesson_available && !['ready', 'completed'].includes(item.latest_status)
    ? '可开始学习 · 最近一次' + latest : item.lesson_available ? '可开始学习' : latest;
  status.dataset.status = item.lesson_available ? 'done'
    : ['queued', 'recognizing', 'pending', 'running', 'generating'].includes(item.latest_status) ? 'doing'
      : ['needs_confirmation', 'unclear', 'figure', 'reviewed'].includes(item.latest_status) ? 'half' : 'unsupported';
  link.append(title, meta, status);
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'sq-history-delete';
  remove.textContent = '删除';
  remove.setAttribute('aria-label', '删除' + (item.summary || '这条拍题记录'));
  remove.addEventListener('click', () => deleteRecord(item, remove));
  row.append(link, remove);
  return row;
}

async function loadHistory(reset = false) {
  if (!pageActive || !session.user || historyLoading && !reset) return;
  if (reset) resetHistory();
  historyLoading = true;
  historyStarted = true;
  const ticket = ++historyTicket;
  $('#sq-history-all').disabled = true;
  $('#sq-history-message').textContent = '正在读取拍题记录…';
  try {
    const response = await session.request('/api/search/problems?limit=20&offset=' + offset);
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (ticket !== historyTicket) return;
    for (const item of data.items) {
      if (historyItems.has(item.search_id) || !session.writable(item.search_id)) continue;
      historyItems.set(item.search_id, item);
      $('#sq-history-list').append(historyRow(item));
    }
    offset += data.items.length;
    $('#sq-history-message').textContent = historyItems.size ? '' : '还没有拍过题，拍一道试试。';
    $('#sq-history-all').hidden = !data.has_more;
    $('#sq-history-all').textContent = '加载更多';
    renderMath($('#sq-history-list'));
  } catch (error) {
    if (ticket !== historyTicket || error.name === 'AbortError') return;
    $('#sq-history-message').textContent = '暂时无法读取拍题记录，请重试。';
    $('#sq-history-all').hidden = false;
    $('#sq-history-all').textContent = '重试';
  } finally {
    if (ticket === historyTicket) { historyLoading = false; $('#sq-history-all').disabled = false; }
  }
}

async function deleteRecord(item, button) {
  const message = item.problem_id ? '删除你拍过的这道题的全部记录和照片？其他题目不受影响。' : '删除这条拍题记录和照片？';
  if (!window.confirm(message)) return;
  const userId = session.user.id;
  button.disabled = true;
  try {
    const response = await session.request('/api/search/problems/' + encodeURIComponent(item.search_id), {method: 'DELETE'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    session.clearProgress(userId, data.deleted_search_ids);
  } catch (error) {
    if (error.name !== 'AbortError') { toast('删除失败，请稍后重试'); button.disabled = false; }
  }
}

async function proceed(action) {
  try {
    if (!await session.login() || !pageActive) return;
    if (action === 'shoot') location.href = 'camera.html';
    else { albumTicket = session.epoch; $('#sq-file').click(); }
  } catch { toast('登录服务暂不可用，请稍后重试'); }
}

async function handOff(file, ticket = session.epoch) {
  const userId = session.user?.id;
  if (!userId || !pageActive || !session.valid(ticket)) return;
  const image = new Image();
  const url = URL.createObjectURL(file);
  try {
    image.src = url;
    await image.decode();
    if (!pageActive || !session.valid(ticket)) return;
    const scale = Math.min(1, 2200 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = Object.assign(document.createElement('canvas'), {width: Math.round(image.naturalWidth * scale), height: Math.round(image.naturalHeight * scale)});
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    sessionStorage.setItem('sq-page', JSON.stringify({user_id: userId, image: canvas.toDataURL('image/jpeg', .88)}));
    location.href = 'camera.html?from=album';
  } catch { if (session.valid(ticket)) toast('照片无法读取或太大，请换一张试试'); }
  finally { URL.revokeObjectURL(url); }
}

document.addEventListener('DOMContentLoaded', async () => {
  renderMath($('.sq-scope'));
  resetHistory();
  $('#sq-file').addEventListener('change', event => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    if (!/^image\//.test(file.type)) return toast('请选择 PNG、JPEG 或 WebP 图片');
    if (file.size > 20 * 1024 * 1024) return toast('图片超过 20 MB，请压缩后再试');
    const ticket = albumTicket;
    albumTicket = null;
    if (ticket !== null) void handOff(file, ticket);
  });
  $('#sq-history-all').addEventListener('click', () => loadHistory());
  document.addEventListener('click', event => {
    if (event.target.closest('[data-shoot]')) { event.preventDefault(); void proceed('shoot'); }
    if (event.target.closest('[data-album]')) void proceed('album');
    if (event.target.closest('[data-login]')) void session.login().catch(() => toast('登录服务暂不可用，请稍后重试'));
  });
  const dock = $('#sq-dock');
  new IntersectionObserver(([entry]) => { dock.hidden = entry.isIntersecting; }).observe($('#sq-capture'));
  window.addEventListener('pagehide', () => { pageActive = false; albumTicket = null; resetHistory(); });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  await session.init(() => { resetHistory(); if (session.user) void loadHistory(); });
  if (session.user && !historyStarted) await loadHistory();
});

window.addEventListener('search-records-deleted', event => {
  if (event.detail.user_id === session.user?.id && pageActive) void loadHistory(true);
});
