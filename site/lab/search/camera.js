/* Question boxes come from the authenticated OCR segmentation API. */
const params = new URLSearchParams(location.search);
const sim = params.get('sim');
const $ = selector => document.querySelector(selector);
const session = window.SearchSession;
const searchFetch = (...args) => session.request(...args);

/* Mock worksheet: known question boxes stand in for the detection service. */
const PAGE = [
  {src: 'sample-q01.png', demo: 'ok'},
  {text: '求函数 y = sin x + cos x 的最大值。', h: 200, demo: 'unsupported'},
  {src: 'sample-q04.png', demo: 'ok'},
  {src: 'sample-q10.png', demo: 'multi'},
  {src: 'sample-q02.png', demo: 'ok'},
  {src: 'sample-q11.png', demo: 'ok'},
];
const MOCK_BANDS = [[.08, .28], [.38, .26], [.66, .26]].map(([y, h]) => ({x: .05, y, w: .9, h, demo: 'ok'}));

let stream = null;
let page = null;
let pageId = null;
let detection = null;
let boxes = [];
let selected = 0;
let crop = null;
let generation = 0;
let captureGeneration = 0;
const pickerTickets = new Map();
let readyGeneration = null;
let loading = false;
let submission = null;
let currentResult = null;
let retryAction = null;
let pendingResult = null;
let rotationLimitedPageId = null;
let submissionIntent = null;
const MIN = .08;

const load = src => new Promise((resolve, reject) => {
  const img = new Image();
  img.onload = () => resolve(img); img.onerror = reject; img.src = src;
});

function toast(text) {
  const el = $('#sq-toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 2400);
}

async function buildPage() {
  const W = 2100, pad = 90, gap = 46, head = 220, number = 110, inner = 1920 - number;
  const imgs = await Promise.all(PAGE.map(item => item.src ? load(item.src) : null));
  const heights = PAGE.map((item, i) => imgs[i] ? imgs[i].naturalHeight * inner / imgs[i].naturalWidth : item.h);
  const H = head + heights.reduce((sum, h) => sum + h + gap, 0) + pad;
  const canvas = Object.assign(document.createElement('canvas'), {width: W, height: H});
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#f3f0e8'; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#2a2a2a'; ctx.textAlign = 'center';
  ctx.font = 'bold 66px "Songti SC", "STSong", serif';
  ctx.fillText('高一数学 · 不等式恒成立专项练习', W / 2, 112);
  ctx.font = '42px "Songti SC", "STSong", serif';
  ctx.fillText('班级 ________    姓名 ________', W / 2, 180);
  ctx.textAlign = 'left';
  ctx.globalCompositeOperation = 'multiply';
  const found = [];
  let y = head;
  PAGE.forEach((item, i) => {
    const h = heights[i];
    ctx.font = '62px "Songti SC", "STSong", serif';
    const baseline = imgs[i] ? y + Math.min(h, 140) / 2 + 22 : y + h / 2 + 20;
    ctx.fillText(`${i + 1}．`, pad, baseline);
    if (imgs[i]) ctx.drawImage(imgs[i], pad + number, y, inner, h);
    else ctx.fillText(item.text, pad + number, baseline);
    found.push({x: (pad - 24) / W, y: (y - 14) / H, w: (number + inner + 48) / W, h: (h + 28) / H, demo: item.demo, number: i + 1});
    y += h + gap;
  });
  ctx.globalCompositeOperation = 'source-over';
  const shade = ctx.createRadialGradient(W / 2, H / 2, H * .3, W / 2, H / 2, H * .8);
  shade.addColorStop(0, 'rgba(0,0,0,0)'); shade.addColorStop(1, 'rgba(60,45,20,.16)');
  ctx.fillStyle = shade; ctx.fillRect(0, 0, W, H);
  return {url: canvas.toDataURL('image/jpeg', .9), boxes: found};
}

/* ---------- 取景 ---------- */
function showDenied() {
  $('#cm-denied').hidden = false;
  $('#cm-hint').hidden = true;
  $('.cm-bar').hidden = true;
}

async function startCamera() {
  const token = session.epoch;
  const capture = ++captureGeneration;
  const current = () => session.valid(token) && capture === captureGeneration;
  if (sim === '1') {
    const built = await buildPage();
    if (!current()) return;
    page = built;
    $('#cm-video').hidden = true;
    Object.assign($('#cm-sim'), {src: page.url, hidden: false});
    return;
  }
  if (sim === 'denied' || !navigator.mediaDevices?.getUserMedia) return showDenied();
  try {
    const captured = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1440}}, audio: false});
    if (!current()) { for (const track of captured.getTracks()) track.stop(); return; }
    stream = captured;
    $('#cm-video').srcObject = stream;
  } catch {
    if (current()) showDenied();
  }
}

function stopCamera() {
  for (const track of stream?.getTracks() || []) track.stop();
  stream = null;
}

const toBlob = async url => (await fetch(url)).blob();

async function shoot() {
  if (!session.user) return;
  const ticket = session.epoch;
  const capture = captureGeneration;
  const current = () => session.valid(ticket) && capture === captureGeneration;
  if (page) {
    const photo = page;
    const blob = await toBlob(photo.url);
    if (current()) return openPick(photo.url, blob, photo.boxes);
    return;
  }
  const video = $('#cm-video');
  if (!video.videoWidth) return;
  const canvas = Object.assign(document.createElement('canvas'), {width: video.videoWidth, height: video.videoHeight});
  canvas.getContext('2d').drawImage(video, 0, 0);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .92));
  if (!current()) return;
  openPick(URL.createObjectURL(blob), blob, MOCK_BANDS);
}

async function fromFile(file) {
  if (!file || !session.user) return;
  if (!/^image\//.test(file.type)) { toast('请选择 PNG、JPEG 或 WebP 图片'); return; }
  openPick(URL.createObjectURL(file), file, MOCK_BANDS);
}

/* A result and its image are installed together; coordinates always refer to that image. */
function pageResult(result) {
  const seconds = Object.values(result.latency_ms || {}).reduce((a, b) => a + b, 0) / 1000;
  const rect = ([x0, y0, x1, y1]) => ({x: x0, y: y0, w: x1 - x0, h: y1 - y0});
  const found = result.regions.map(r => ({...rect(r.box), number: r.number, label: r.label, crop: rect(r.crop || r.box)}));
  const note = result.mode === 'uncertain' || !found.length
    ? '未能准确定位题目，请框选完整题干和选项；有题目配图时一并框入。'
    : `OCR 切题 ${seconds.toFixed(1)} 秒 · ${found.length} 道` + (result.mode === 'whole_content' ? ' · 没找到题号，请确认选区只包含一道题' : '');
  return {pageId: result.page_id, url: result.preview_url || result.image_url || `/api/search/pages/${result.page_id}/image`,
    found, note, orientation: result.orientation, offline: false};
}

class PageDetectionError extends Error {}

function uploadErrorMessage(status, detail) {
  if (detail === 'page.pixels') return '照片分辨率超过 3200 万像素，请缩小图片后重试。';
  if (status === 413) return '照片太大，请压缩后重试。';
  if (detail === 'page.not_an_image') return '图片格式不受支持或文件已损坏，请改用 JPEG、PNG 或 WebP。';
  if (detail === 'page.size') return '照片内容为空，请重新选择照片。';
  if (detail.startsWith('ocr.unavailable')) return '识别服务暂不可用，请稍后重试。';
  return window.SearchErrors.message(detail, '照片处理失败，请稍后重试。');
}

async function detect(blob, fallback, url) {
  let response;
  try {
    response = await searchFetch('/api/search/pages', {method: 'POST', body: blob, headers: {'Content-Type': blob.type || 'image/jpeg'}});
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new PageDetectionError('暂时无法连接识别服务，请检查网络后重试。');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new PageDetectionError(uploadErrorMessage(response.status, typeof body?.detail === 'string' ? body.detail : ''));
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new PageDetectionError('识别服务返回了无效数据，请重试。');
  }
  return pageResult(result);
}

/* ---------- 选题 ---------- */
function syncControls() {
  const disabled = loading || !!submission || readyGeneration !== generation;
  for (const id of ['#cm-go', '#cm-crop-go', '#cm-whole', '#cm-manual', '#cm-crop-cancel']) $(id).disabled = disabled;
  $('#cm-rotate').disabled = disabled || !pageId || !!pendingResult || pageId === rotationLimitedPageId;
  for (const id of ['#cm-go', '#cm-crop-go']) $(id).innerHTML = `${currentResult?.offline ? '查看模拟流程' : '学这道题'} <span aria-hidden="true">→</span>`;
  $('#cm-whole').textContent = currentResult?.offline ? '整图查看模拟流程' : '使用整张图';
  $('#cm-retry').disabled = loading || !!submission;
  $('#cm-pick').setAttribute('aria-busy', String(loading || !!submission));
}

function beginDetection() {
  const token = ++generation;
  clearTimeout(toast.timer);
  $('#sq-toast').hidden = true;
  loading = true;
  submission = null;
  readyGeneration = null;
  pageId = null;
  boxes = [];
  crop = null;
  selected = 0;
  retryAction = null;
  pendingResult = null;
  $('#cm-boxes').innerHTML = '';
  $('#cm-boxes').classList.remove('is-cropping');
  $('#cm-chips').innerHTML = '';
  $('#cm-chosen-img').removeAttribute('src');
  for (const id of ['#cm-crop', '#cm-choose', '#cm-cropping', '#cm-proto-note', '#cm-orientation-note', '#cm-retry']) $(id).hidden = true;
  $('#cm-title').textContent = '正在处理照片';
  $('#cm-finding').hidden = false;
  $('#cm-finding-text').hidden = false;
  document.body.dataset.state = 'pick';
  $('#cm-shoot').hidden = true;
  $('#cm-pick').hidden = false;
  syncControls();
  return token;
}

async function decodedPhoto(url) {
  const image = Object.assign(document.createElement('img'), {id: 'cm-photo', alt: '拍到的照片', draggable: false, src: url});
  await image.decode();
  if (!image.naturalWidth || !image.naturalHeight) throw new Error('Empty image');
  return image;
}

function installPage(result, image, token, previous = null, announceOrientation = false) {
  if (token !== generation) return;
  const photo = $('#cm-photo');
  if (photo !== image) photo.replaceWith(image);
  image.hidden = false;
  currentResult = result;
  pendingResult = null;
  retryAction = null;
  $('#cm-retry').hidden = true;
  pageId = result.pageId;
  boxes = result.found;
  readyGeneration = token;
  loading = false;
  Object.assign($('#cm-proto-note'), {textContent: result.note, hidden: false});
  Object.assign($('#cm-orientation-note'), {textContent: '方向未确定，请检查文字朝向；可点「顺时针 90°」调整。', hidden: result.orientation?.status !== 'uncertain'});
  $('#cm-finding').hidden = true;
  $('#cm-finding-text').hidden = true;
  syncControls();
  if (announceOrientation && result.orientation?.status === 'corrected') toast('已自动转正');
  if (!boxes.length) { startCrop(previous?.crop, true); return; }
  renderBoxes();
  $('#cm-choose').hidden = false;
  /* Students aim at the question they want, so preselect the box nearest the middle of the shot. */
  const dist = box => Math.abs(box.y + box.h / 2 - .5);
  select(previous?.selected ?? boxes.reduce((best, box, i) => dist(box) < dist(boxes[best]) ? i : best, 0), true);
  if (previous?.crop) startCrop(previous.crop, true);
}

function pageSelection() {
  if (readyGeneration !== generation || !currentResult) return null;
  return {result: currentResult, image: $('#cm-photo'), selected, crop: crop && {...crop}};
}

async function loadResult(result, token, previous = null) {
  if (token !== generation) return;
  pendingResult = result;
  try {
    const image = await decodedPhoto(result.url);
    installPage(result, image, token, null, true);
  } catch {
    if (token !== generation) return;
    if (previous) {
      installPage(previous.result, previous.image, token, previous);
      toast('旋转后的照片加载失败，已保留原图和选区，请重试加载');
    } else {
      loading = false;
      readyGeneration = null;
      pageId = null;
      currentResult = null;
      boxes = [];
      crop = null;
      $('#cm-boxes').innerHTML = '';
      for (const id of ['#cm-finding', '#cm-finding-text', '#cm-crop', '#cm-choose', '#cm-cropping']) $(id).hidden = true;
      $('#cm-title').textContent = '照片预览加载失败';
      Object.assign($('#cm-proto-note'), {textContent: '处理后的照片未能加载，请重试加载预览。', hidden: false});
    }
    /* Keep the completed OCR/rotation result. Retrying downloads only its existing preview. */
    pendingResult = result;
    retryAction = () => retryResult(result, token);
    Object.assign($('#cm-retry'), {textContent: previous ? '重试加载旋转照片' : '重试加载照片', hidden: false});
    syncControls();
  }
}

function retryResult(result, expectedGeneration) {
  if (loading || submission || expectedGeneration !== generation || pendingResult !== result) return;
  const previous = pageSelection();
  const token = beginDetection();
  detection = loadResult(result, token, previous);
  return detection;
}

async function openPick(url, blob, fallback) {
  stopCamera();
  currentResult = null;
  submissionIntent = null;
  const token = beginDetection();
  $('#cm-photo').hidden = true;
  /* Show a local preview while OCR runs, without attaching coordinates or enabling actions. */
  decodedPhoto(url).then(image => {
    if (token !== generation || readyGeneration === token) return;
    $('#cm-photo').replaceWith(image);
    image.hidden = false;
  }).catch(() => {});
  detection = (async () => {
    try {
      const result = await detect(blob, fallback, url);
      if (token !== generation) return;
      await loadResult(result, token);
    } catch (error) {
      if (token !== generation) return;
      loading = false;
      $('#cm-finding').hidden = true;
      $('#cm-finding-text').hidden = true;
      $('#cm-title').textContent = '照片识别失败';
      Object.assign($('#cm-proto-note'), {
        textContent: error instanceof PageDetectionError ? error.message : '识别服务返回了无效数据，请重试或重新选择照片。', hidden: false,
      });
      retryAction = () => openPick(url, blob, fallback);
      Object.assign($('#cm-retry'), {textContent: '重试识别', hidden: false});
      syncControls();
    }
  })();
  return detection;
}

async function rotatePage() {
  if (loading || submission || pendingResult || readyGeneration !== generation || !pageId || pageId === rotationLimitedPageId) return;
  const previous = pageSelection();
  const sourcePageId = pageId;
  const token = beginDetection();
  detection = (async () => {
    try {
      const response = await searchFetch(`/api/search/pages/${sourcePageId}/rotate`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({degrees: 90}),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(body.detail || `HTTP ${response.status}`));
      const result = pageResult(body);
      if (token !== generation) return;
      await loadResult(result, token, previous);
    } catch (error) {
      if (token !== generation) return;
      const limited = error.message === 'page.rotation_limit';
      if (limited) rotationLimitedPageId = sourcePageId;
      installPage(previous.result, previous.image, token, previous);
      const message = window.SearchErrors.message(error.message,
        limited ? '已达到连续旋转次数上限，请重新选择照片' : '旋转失败，已保留原图和选区，请重试');
      if (limited) Object.assign($('#cm-proto-note'), {textContent: message, hidden: false});
      toast(message);
    }
  })();
  return detection;
}

const label = i => boxes[i].label || boxes[i].number || i + 1;
const questionLabel = i => boxes[i].label || `第 ${label(i)} 题`;
const escapeLabel = value => String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

function renderBoxes() {
  $('#cm-boxes').innerHTML = boxes.map((box, i) =>
    `<button type="button" class="cm-box" data-box="${i}" aria-label="${escapeLabel(questionLabel(i))}" style="left:${box.x * 100}%;top:${box.y * 100}%;width:${box.w * 100}%;height:${box.h * 100}%;animation-delay:${i * 60}ms"><b>${escapeLabel(label(i))}</b></button>`).join('');
  $('#cm-chips').innerHTML = boxes.map((_, i) => `<button type="button" role="tab" data-box="${i}">${escapeLabel(label(i))}</button>`).join('');
}

function cropUrl(rect, max) {
  const img = $('#cm-photo');
  const sx = rect.x * img.naturalWidth, sy = rect.y * img.naturalHeight, sw = rect.w * img.naturalWidth, sh = rect.h * img.naturalHeight;
  const scale = Math.min(1, max / Math.max(sw, sh));
  const canvas = Object.assign(document.createElement('canvas'), {width: Math.round(sw * scale), height: Math.round(sh * scale)});
  canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', .9);
}

function select(i, restoring = false) {
  if (loading || (!restoring && submission) || readyGeneration !== generation || !boxes[i]) return;
  selected = i;
  for (const el of document.querySelectorAll('.cm-box')) el.setAttribute('aria-pressed', String(Number(el.dataset.box) === i));
  for (const el of $('#cm-chips').children) el.setAttribute('aria-selected', String(Number(el.dataset.box) === i));
  $('#cm-chips').children[i]?.scrollIntoView({block: 'nearest', inline: 'center'});
  $('#cm-chosen-img').src = cropUrl(boxes[i].crop || boxes[i], 900);
  $('#cm-title').textContent = questionLabel(i);
}

async function go(rect, expectedGeneration = readyGeneration) {
  if (loading || submission || readyGeneration !== generation || expectedGeneration !== generation) return;
  const pending = {generation: expectedGeneration};
  submission = pending;
  const requestedRect = {...rect};
  syncControls();
  try {
    await detection;
    if (submission !== pending || expectedGeneration !== generation || readyGeneration !== generation || !currentResult) return;
    if (!pageId) return;
    const box = [requestedRect.x, requestedRect.y, requestedRect.x + requestedRect.w, requestedRect.y + requestedRect.h];
    const identity = JSON.stringify([session.user.id, pageId, box]);
    if (submissionIntent?.identity !== identity) submissionIntent = {identity, id: crypto.randomUUID()};
    const response = await searchFetch('/api/search/problems', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({page_id: pageId, box, client_request_id: submissionIntent.id}),
    });
    const body = await response.json().catch(() => ({}));
    if (submission !== pending || expectedGeneration !== generation) return;
    if (response.ok) { location.href = `problem.html?search=${body.search_id}`; return; }
    const detail = String(body.detail || response.status);
    if (detail === 'search.request_retired') submissionIntent = null;
    toast(window.SearchErrors.message(detail, '提交失败，请稍后重试。'));
  } catch {
    if (submission === pending && expectedGeneration === generation) toast('提交失败，请检查连接后重试');
  } finally {
    if (submission === pending) { submission = null; syncControls(); }
  }
}

/* ---------- 手动框选 ---------- */
function placeCrop() {
  Object.assign($('#cm-crop').style, {left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%`});
}

function startCrop(previous = null, restoring = false) {
  if (loading || (!restoring && submission) || readyGeneration !== generation) return;
  const base = previous?.w ? previous : boxes[selected]?.crop || boxes[selected] || {x: .08, y: .3, w: .84, h: .3};
  crop = {x: base.x, y: base.y, w: base.w, h: base.h};
  placeCrop();
  $('#cm-crop').hidden = false;
  $('#cm-boxes').classList.add('is-cropping');
  $('#cm-choose').hidden = true;
  $('#cm-cropping').hidden = false;
  $('#cm-title').textContent = '手动框选';
}

function endCrop() {
  if (loading || submission || readyGeneration !== generation) return;
  if (!boxes.length) return reshoot();
  crop = null;
  $('#cm-crop').hidden = true;
  $('#cm-boxes').classList.remove('is-cropping');
  $('#cm-cropping').hidden = true;
  $('#cm-choose').hidden = false;
  select(selected);
}

function bindCrop() {
  const stage = $('#cm-stage');
  let drag = null;
  stage.addEventListener('pointerdown', event => {
    if (loading || submission || readyGeneration !== generation || !crop || !event.target.closest('#cm-crop')) return;
    event.preventDefault();
    stage.setPointerCapture(event.pointerId);
    drag = {generation, handle: event.target.dataset.handle || 'move', start: {...crop}, x: event.clientX, y: event.clientY, rect: stage.getBoundingClientRect()};
  });
  stage.addEventListener('pointermove', event => {
    if (!drag) return;
    if (drag.generation !== generation || loading || submission) { drag = null; return; }
    const dx = (event.clientX - drag.x) / drag.rect.width, dy = (event.clientY - drag.y) / drag.rect.height;
    const s = drag.start, clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    if (drag.handle === 'move') {
      crop = {x: clamp(s.x + dx, 0, 1 - s.w), y: clamp(s.y + dy, 0, 1 - s.h), w: s.w, h: s.h};
    } else {
      let left = s.x, top = s.y, right = s.x + s.w, bottom = s.y + s.h;
      if (drag.handle.includes('w')) left = clamp(left + dx, 0, right - MIN);
      if (drag.handle.includes('e')) right = clamp(right + dx, left + MIN, 1);
      if (drag.handle.includes('n')) top = clamp(top + dy, 0, bottom - MIN);
      if (drag.handle.includes('s')) bottom = clamp(bottom + dy, top + MIN, 1);
      crop = {x: left, y: top, w: right - left, h: bottom - top};
    }
    placeCrop();
  });
  const end = () => { drag = null; };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
}

function reshoot() {
  generation++;
  readyGeneration = null;
  submission = null;
  location.href = sim ? `camera.html?sim=${sim}` : 'camera.html';
}

function clearPrivateCamera() {
  captureGeneration++;
  pickerTickets.clear();
  generation++;
  readyGeneration = null;
  submission = null;
  submissionIntent = null;
  page = null;
  pageId = null;
  currentResult = null;
  pendingResult = null;
  retryAction = null;
  boxes = [];
  stopCamera();
  $('#cm-video').srcObject = null;
  for (const selector of ['#cm-photo', '#cm-chosen-img', '#cm-sim']) $(selector).removeAttribute('src');
  $('#cm-boxes').replaceChildren();
  $('#cm-shoot').hidden = true;
  $('#cm-pick').hidden = true;
}

document.addEventListener('DOMContentLoaded', async () => {
  const lifecycle = captureGeneration;
  window.addEventListener('pagehide', clearPrivateCamera);
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  $('#cm-shutter').addEventListener('click', shoot);
  for (const id of ['#cm-album', '#cm-system']) $(id).addEventListener('change', event => {
    const file = event.target.files[0], ticket = pickerTickets.get(id);
    event.target.value = '';
    pickerTickets.delete(id);
    if (ticket && ticket.capture === captureGeneration && session.valid(ticket.epoch)) void fromFile(file);
  });
  $('#cm-retake').addEventListener('click', reshoot);
  $('#cm-rotate').addEventListener('click', rotatePage);
  $('#cm-retry').addEventListener('click', () => retryAction?.());
  $('#cm-whole').addEventListener('click', () => go({x: 0, y: 0, w: 1, h: 1, demo: 'ok'}));
  document.addEventListener('click', event => {
    const picker = event.target.closest('[data-file]');
    if (picker) {
      const capture = captureGeneration;
      void session.login().then(user => {
        if (!user || capture !== captureGeneration) return;
        const id = `#${picker.dataset.file}`;
        pickerTickets.set(id, {epoch: session.epoch, capture});
        $(id).click();
      }).catch(() => toast('登录服务暂不可用'));
    }
    const target = event.target.closest('[data-box]');
    if (target) select(Number(target.dataset.box));
  });
  $('#cm-go').addEventListener('click', () => { if (boxes[selected]) go({...boxes[selected].crop || boxes[selected], demo: boxes[selected].demo}); });
  $('#cm-manual').addEventListener('click', () => startCrop());
  $('#cm-crop-cancel').addEventListener('click', endCrop);
  $('#cm-crop-go').addEventListener('click', () => { if (crop) go({...crop, demo: boxes[selected]?.demo}); });
  bindCrop();

  await session.init((_next, previous) => {
    if (!previous) return;
    clearPrivateCamera();
    location.href = './';
  });
  try { if (!await session.login()) { location.href = './'; return; } }
  catch { toast('登录服务暂不可用，请返回后重试'); return; }
  if (lifecycle !== captureGeneration) return;
  let handoff;
  try { handoff = JSON.parse(sessionStorage.getItem('sq-page') || 'null'); } catch {}
  sessionStorage.removeItem('sq-page');
  if (params.get('from') === 'album' && handoff?.user_id === session.user.id) {
    const token = session.epoch;
    const capture = captureGeneration;
    $('#cm-video').hidden = true;
    const blob = await toBlob(handoff.image);
    if (session.valid(token) && capture === captureGeneration) await openPick(handoff.image, blob, []);
    return;
  }
  if (params.get('demo') === 'page') {
    const token = session.epoch;
    const capture = captureGeneration;
    buildPage().then(async built => {
      const blob = await toBlob(built.url);
      if (!session.valid(token) || capture !== captureGeneration) return;
      page = built; openPick(page.url, blob, page.boxes);
    });
    return;
  }
  startCamera();
});
