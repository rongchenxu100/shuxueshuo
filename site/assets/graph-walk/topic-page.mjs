import {mountWalk, restoreWalkProgress, disposeWalk} from './walk.mjs?v=20261102-piecewise-j1';
import {createRecorder} from '../learning/practice-records.js?v=20261026-domain-powers';
import {isPreview} from '../practice/learning-mode.mjs';
import {routeRecordActions} from './practice-route.mjs?v=20261030-range-selection';
import {checkPracticeCompatibility} from '../learning/practice-compatibility.mjs';

const config = JSON.parse(document.querySelector('#graph-walk-page').textContent);
const read = async url => {
  const response = await fetch(url, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw Error('课包暂时无法读取，请刷新重试。');
  return response.json();
};
try {
  const [bundle, replay] = await Promise.all([read(config.bundleUrl), read(config.replayUrl)]);
  if (bundle.problemId !== config.problemId) throw Error('课包身份与题页不一致。');
  const route = Object.keys(bundle.routes)[0], preview = config.preview === true || isPreview(location.search);
  let mountedOwner = null, mounting = false, pendingHistory = null, epoch = 0;
  let recordedRoute = route;
  let recorder = null, recording = false, pendingRecords = [];
  const owner = () => window.SiteAuth?.user?.id || 'guest';
  const model = {id: bundle.problemId, runtime: 'graph-walk',
    methods: Object.values(bundle.routes).map(item => ({id: item.id, label: item.label})),
    routes: Object.fromEntries(Object.entries(bundle.routes).map(([id, value]) => [id, [...bundle.intro, ...value.steps]]))};
  const onResume = history => {
    recordedRoute = history.route_id;
    if (mounting || mountedOwner !== owner()) { pendingHistory = {owner: owner(), history}; return true; }
    return restoreWalkProgress(history);
  };
  const onConfirmed = history => {
    if (history.status !== 'completed') return;
    document.querySelector('#gw-completion').dataset.learningCompleted = 'true';
    window.dispatchEvent(new CustomEvent('practice-completed', {detail: {problemId: bundle.problemId}}));
  };
  const notice = document.createElement('aside');
  notice.className = 'practice-record-status'; notice.setAttribute('role', 'status');
  notice.hidden = true;
  const message = document.createElement('span'), retry = document.createElement('button');
  retry.type = 'button'; retry.textContent = '重试保存连接';
  notice.append(message, retry);
  document.querySelector('.gw-workspace').append(notice);
  async function enableRecording() {
    if (preview || recorder || recording) return;
    recording = true; retry.disabled = true;
    try {
      const problem = await read(`/knowledge/teaching/problems/${encodeURIComponent(bundle.problemId)}.json`);
      const access = await checkPracticeCompatibility(bundle, problem, read);
      recorder = createRecorder(model, onResume, {...access, onConfirmed});
      for (const {route, actions} of pendingRecords) for (const item of actions) recorder.graphAnswer(route, item.decision, item.answer);
      pendingRecords = []; notice.hidden = true;
    } catch (error) {
      message.textContent = `${error.message} 本地练习可以继续。`;
      notice.hidden = false;
    } finally { recording = false; retry.disabled = false; }
  }
  retry.onclick = enableRecording;
  function record(action, view) {
    if (preview) return;
    const planned = routeRecordActions(bundle, view, action, recordedRoute);
    if (recorder) for (const item of planned.actions) recorder.graphAnswer(planned.route, item.decision, item.answer);
    else pendingRecords.push(planned);
    recordedRoute = planned.route;
  }
  async function mount() {
    const ticket = ++epoch, currentOwner = owner();
    mounting = true;
    await mountWalk({bundle, replay, actor: 'student', practicePage: null, revealGraph: true,
      progressScope: `sss-topic:${preview ? 'preview:' : ''}${currentOwner}:`,
      onAnswer: record, onRouteChange: view => record(null, view),
      onReset: () => { recordedRoute = route; pendingRecords = []; recorder?.reset(); }});
    if (ticket !== epoch) return;
    mounting = false; mountedOwner = currentOwner;
    if (pendingHistory?.owner === currentOwner) {
      const history = pendingHistory.history; pendingHistory = null;
      if (!restoreWalkProgress(history)) throw Error('已保存的进度与当前课包不同，请重新开始。');
    }
  }
  window.addEventListener('site-auth-change', () => {
    if (owner() === mountedOwner && !mounting) return;
    if (mountedOwner && mountedOwner !== 'guest') pendingRecords = [];
    disposeWalk(); void mount().catch(showError);
  });
  await mount();
  // Optional recording must never gate rendering of a published static course.
  void enableRecording();
  await import('../learning/learning-marks.js?v=20261026-domain-powers');
} catch (error) { showError(error); }

function showError(error) {
  document.querySelector('#gw-loading').hidden = true;
  document.querySelector('#gw-error').hidden = false;
  document.querySelector('#gw-error p').textContent = error.message;
}
