import {mountWalk, restoreWalkProgress, disposeWalk} from './walk.mjs?v=20261026-mobile-math';
import {createRecorder} from '../learning/practice-records.js?v=20261026-mobile-math';
import {isPreview} from '../practice/learning-mode.mjs';

const config = JSON.parse(document.querySelector('#graph-walk-page').textContent);
const read = async url => {
  const response = await fetch(url, {cache: 'no-store'});
  if (!response.ok) throw Error('课包暂时无法读取，请刷新重试。');
  return response.json();
};
try {
  const [bundle, replay, version] = await Promise.all([read(config.bundleUrl), read(config.replayUrl), read('/knowledge/teaching/version.json')]);
  if (bundle.problemId !== config.problemId) throw Error('课包身份与题页不一致。');
  const route = Object.keys(bundle.routes)[0], preview = isPreview(location.search);
  let mountedOwner = null, mounting = false, pendingHistory = null, epoch = 0;
  const owner = () => window.SiteAuth?.user?.id || 'guest';
  const model = {id: bundle.problemId, runtime: 'graph-walk',
    methods: Object.values(bundle.routes).map(item => ({id: item.id, label: item.label})),
    routes: Object.fromEntries(Object.entries(bundle.routes).map(([id, value]) => [id, [...bundle.intro, ...value.steps]]))};
  const recorder = preview ? null : createRecorder(model, history => {
    if (mounting || mountedOwner !== owner()) { pendingHistory = {owner: owner(), history}; return true; }
    return restoreWalkProgress(history);
  }, {contentVersion: version.content_version, onConfirmed: history => {
    if (history.status !== 'completed') return;
    document.querySelector('#gw-completion').dataset.learningCompleted = 'true';
    window.dispatchEvent(new CustomEvent('practice-completed', {detail: {problemId: bundle.problemId}}));
  }});
  async function mount() {
    const ticket = ++epoch, currentOwner = owner();
    mounting = true;
    await mountWalk({bundle, replay, actor: 'student', practicePage: null, revealGraph: true,
      progressScope: `sss-topic:${preview ? 'preview:' : ''}${currentOwner}:`,
      onAnswer: action => recorder?.graphAnswer(route, action.decision, action.answer),
      onReset: () => recorder?.reset()});
    if (ticket !== epoch) return;
    mounting = false; mountedOwner = currentOwner;
    if (pendingHistory?.owner === currentOwner) {
      const history = pendingHistory.history; pendingHistory = null;
      if (!restoreWalkProgress(history)) throw Error('已保存的进度与当前课包不同，请重新开始。');
    }
  }
  window.addEventListener('site-auth-change', () => {
    if (owner() === mountedOwner && !mounting) return;
    disposeWalk(); void mount().catch(showError);
  });
  await mount();
  await import('../learning/learning-marks.js?v=20261026-mobile-math');
} catch (error) { showError(error); }

function showError(error) {
  document.querySelector('#gw-loading').hidden = true;
  document.querySelector('#gw-error').hidden = false;
  document.querySelector('#gw-error p').textContent = error.message;
}
