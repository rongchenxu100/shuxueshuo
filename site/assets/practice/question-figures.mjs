/* Original question pictures, shared by authored lessons and private photo lessons.
   This is a display contract: it cannot validate a graph or choose an answer. */
const ID = /^[a-z][a-z0-9-]{0,63}$/;
const HASH = /^[a-f0-9]{64}$/;
const SCOPE = /^\/root(?:\/children\/[0-9]+)*$/;
const TARGET = /^\/root(?:\/children\/[0-9]+)*\/goals\/[0-9]+$/;

export function figureLabel(figure, quality) {
  if (figure.role === 'source') return quality === 'processed' ? '识别用图（原始裁图未保留）' : '原始裁图';
  return figure.role === 'option' ? `选项 ${figure.label} 的原图` : '题干配图';
}

export function projectFigures(manifest, {searchId = null, targetRef = null} = {}) {
  const bad = () => { throw new Error('题图清单与当前题目不匹配，请重新打开。'); };
  if (!manifest || manifest.schema_version !== 'question-figures/v1' || !HASH.test(manifest.content_id) ||
      !HASH.test(manifest.source?.sha256) || !['original', 'processed'].includes(manifest.source?.quality) ||
      ![manifest.source?.width, manifest.source?.height].every(n => Number.isInteger(n) && n > 0 && n <= 20000) ||
      !Array.isArray(manifest.figures) || !manifest.figures.length || manifest.figures.length > 40 ||
      (searchId !== null && !/^[a-f0-9]{12}$/.test(searchId)) || (targetRef !== null && !TARGET.test(targetRef))) bad();
  const ids = new Set(), optionIds = new Set(), labels = new Set();
  for (const figure of manifest.figures) {
    if (!ID.test(figure.id) || ids.has(figure.id) || !SCOPE.test(figure.scope_ref) ||
        !['source', 'statement', 'option', 'workspace'].includes(figure.role) ||
        !Array.isArray(figure.box) || figure.box.length !== 4 ||
        !figure.box.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1) ||
        figure.box[0] >= figure.box[2] || figure.box[1] >= figure.box[3]) bad();
    ids.add(figure.id);
    const pixels = figure.box.map((n, i) => Math.round(n * (i % 2 ? manifest.source.height : manifest.source.width)));
    if (pixels[0] >= pixels[2] || pixels[1] >= pixels[3]) bad();
    if (figure.target_ref && (!TARGET.test(figure.target_ref) || figure.target_ref.split('/goals/')[0] !== figure.scope_ref)) bad();
    if (figure.role === 'option') {
      const key = `${figure.target_ref}:${figure.option_id}`, label = `${figure.target_ref}:${figure.label}`;
      if (!TARGET.test(figure.target_ref) || !ID.test(figure.option_id) || !/^[A-Z]$/.test(figure.label) ||
          optionIds.has(key) || labels.has(label)) bad();
      optionIds.add(key); labels.add(label);
    } else if (figure.option_id !== undefined || figure.label !== undefined) bad();
    // Never accept a private URL in a public bundle, a different upload, or an arbitrary URL.
    if (searchId !== null) {
      if (figure.image_url !== `/api/search/problems/${searchId}/figures/${figure.id}?version=${manifest.content_id}`) bad();
    } else if (!/^\/assets\/question-figures\/(?:[a-z0-9_-]+\/)*[a-z0-9_-]+\.png$/.test(figure.image_url)) bad();
  }
  const sources = manifest.figures.filter(row => row.role === 'source');
  const source = sources[0];
  if (sources.length !== 1 || source.id !== 'original' || source.scope_ref !== '/root' ||
      source.target_ref || String(source.box) !== '0,0,1,1') bad();
  const scope = targetRef?.split('/goals/')[0];
  const rows = manifest.figures.filter(row => ['statement', 'option'].includes(row.role) &&
    (!targetRef || (row.target_ref ? row.target_ref === targetRef : scope === row.scope_ref || scope.startsWith(`${row.scope_ref}/children/`))));
  return {source, rows, quality: manifest.source.quality, contentId: manifest.content_id};
}

export function mountQuestionFigures(host, manifest, options = {}) {
  const view = projectFigures(manifest, options);
  if (options.statementOnly) {
    view.rows = view.rows.filter(row => row.role === 'statement');
    if (!view.rows.length) throw new Error('缺少这道题的原图，请重新打开。');
  }
  const doc = host.ownerDocument;
  let disposed = false, opener = null;
  const pictures = [];
  const requiredPictures = [];
  options.onReady?.(false);
  const reportReady = () => options.onReady?.(requiredPictures.length > 0 && requiredPictures.every(p => p.complete && p.naturalWidth > 0));
  const element = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  host.replaceChildren();
  host.classList.add('qf-panel');
  host.dataset.figureVersion = view.contentId;
  host.setAttribute('aria-label', '原题图片');
  const dialog = element('dialog', 'qf-viewer');
  dialog.setAttribute('aria-label', '放大查看原题图片');
  const close = element('button', 'qf-close', '关闭图片');
  close.type = 'button';
  const enlarged = element('img');
  dialog.append(close, enlarged);
  doc.body.append(dialog);
  const onClose = () => {
    enlarged.removeAttribute('src');
    if (!disposed && opener?.isConnected) opener.focus();
  };
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', onClose);
  const show = (row, button) => {
    if (disposed) return;
    opener = button;
    enlarged.alt = figureLabel(row, view.quality);
    enlarged.src = row.image_url;
    dialog.showModal();
    close.focus();
  };
  const card = (row, required = true) => {
    const label = figureLabel(row, view.quality);
    const selection = row.role === 'option' && options.selection;
    const figure = element('figure', 'qf-picture');
    figure.dataset.figureId = row.id;
    figure.dataset.figureRole = row.role;
    if (row.option_id) figure.dataset.optionId = row.option_id;
    if (row.target_ref) figure.dataset.targetRef = row.target_ref;
    const button = element('button', selection ? 'qf-select' : 'qf-open');
    button.type = 'button';
    button.setAttribute('aria-label', selection ? `选择 ${row.label}` : `放大${label}`);
    const zoom = selection ? element('button', 'qf-zoom', '放大') : button;
    if (selection) {
      figure.classList.add('is-selectable');
      button.dataset.choice = selection.field;
      button.dataset.value = row.option_id;
      button.setAttribute('aria-pressed', String(row.option_id === selection.selected));
      zoom.type = 'button';
      zoom.setAttribute('aria-label', `放大${label}`);
    }
    const picture = element('img');
    pictures.push(picture);
    if (required) requiredPictures.push(picture);
    picture.alt = label;
    picture.decoding = 'async';
    picture.src = row.image_url;
    const error = element('p', 'qf-image-error', '图片未能加载，请重新打开题目。');
    error.hidden = true;
    picture.addEventListener('error', () => {
      if (!disposed) { error.hidden = false; button.disabled = true; zoom.disabled = true; if (required) options.onReady?.(false); }
    });
    picture.addEventListener('load', () => { if (!disposed) reportReady(); });
    zoom.addEventListener('click', () => show(row, zoom));
    if (selection) button.append(element('span', 'qf-select-label', `选项 ${row.label}`));
    button.append(picture);
    if (selection) {
      button.append(element('span', 'qf-select-state', row.option_id === selection.selected ? `✓ 已选择 ${row.label}` : `选择 ${row.label}`));
      figure.append(button, zoom, error);
    } else figure.append(element('figcaption', '', label), button, error);
    return figure;
  };
  if (view.rows.length) {
    const grid = element('div', 'qf-grid');
    if (options.statementOnly) grid.classList.add('qf-statement-grid');
    for (const row of view.rows) grid.append(card(row));
    host.append(grid);
    if (!options.statementOnly) {
      const original = element('details', 'qf-original');
      original.append(element('summary', '', '查看原始裁图'), card(view.source, false));
      host.append(original);
    }
  } else {
    host.append(card(view.source));
    host.append(element('p', 'qf-note', '请确认题干与全部选项都在图中。跨页题暂不支持合并。'));
  }
  if (view.quality === 'processed') host.append(element('p', 'qf-note', '这条旧记录只保留了识别用图。若细节不清，请重新拍摄。'));
  reportReady();
  return () => {
    disposed = true;
    for (const picture of [...pictures, enlarged]) picture.removeAttribute('src');
    if (dialog.open) dialog.close();
    dialog.remove();
    host.replaceChildren();
    delete host.dataset.figureVersion;
    host.classList.remove('qf-panel');
  };
}
