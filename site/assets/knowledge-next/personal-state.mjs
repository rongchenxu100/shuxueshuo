import {ABILITY_KINDS, learningApi} from './learning-model.mjs';

const preferenceKey = id => `sss-knowledge-personal:${id}`;

// Only preferences persist. Assessments and evidence never enter localStorage.
// All consumers in one page share this store, including dynamically drawn nodes.
export function createPersonalState({request, storage, preview = false}) {
  let epoch = 0, controller, pending;
  let userId = null, enabled = false, phase = preview ? 'preview' : 'anonymous';
  let nodes = new Map(), progress = new Map(), progressErrors = new Map();
  let contentVersion = null, error = null, revision = 0;
  const listeners = new Set(), progressPending = new Map();
  let queued = new Set(), batchScheduled = false;
  const snapshot = () => ({userId, enabled, phase, nodes, progress, progressErrors, contentVersion, error, revision});
  const emit = () => { for (const listener of listeners) listener(snapshot()); };
  const allowed = id => { try { return storage?.getItem(preferenceKey(id)) !== 'off'; } catch { return true; } };
  function clear(nextPhase) {
    controller?.abort();
    controller = new AbortController();
    epoch++; revision++;
    pending = null; nodes = new Map(); progress = new Map(); progressErrors = new Map();
    contentVersion = null; error = null; phase = nextPhase;
    for (const entry of progressPending.values()) entry.resolve(null);
    progressPending.clear(); queued.clear();
  }
  async function load() {
    if (preview || !userId || !enabled) return snapshot();
    if (pending) return pending;
    if (phase === 'ready') return snapshot();
    phase = 'loading'; error = null; emit();
    const stamp = epoch, owner = userId, signal = controller.signal;
    pending = (async () => {
      try {
        // These are live, read-only records keyed by stable node IDs, not grades
        // against the static article. Unrelated publications must not hide them.
        const result = await request('/nodes', {user: owner, signal});
        if (stamp !== epoch) return snapshot();
        nodes = new Map(result.nodes.filter(node => ABILITY_KINDS.includes(node.kind)).map(node => [node.node_id, node]));
        contentVersion = result.content_version; phase = 'ready'; revision++;
      } catch (cause) {
        if (stamp !== epoch) return snapshot();
        nodes = new Map(); progress = new Map(); contentVersion = null;
        phase = 'error'; error = cause; revision++;
      } finally {
        if (stamp === epoch) { pending = null; emit(); }
      }
      return snapshot();
    })();
    return pending;
  }
  async function flushProgress() {
    batchScheduled = false;
    const scopes = [...queued]; queued.clear();
    if (!scopes.length || phase !== 'ready') return;
    const stamp = epoch, owner = userId;
    const entries = new Map(scopes.map(id => [id, progressPending.get(id)]));
    try {
      const query = new URLSearchParams(); scopes.forEach(id => query.append('scope', id));
      const result = await request(`/progress/batch?${query}`, {user: owner, signal: controller.signal});
      if (stamp !== epoch) return;
      const rows = new Map(result.progress.map(row => [row.scope, row]));
      if (scopes.some(id => !rows.has(id))) throw Error('部分目录进度未返回，请重试。');
      progress = new Map([...progress, ...rows]);
      for (const id of scopes) { progressErrors.delete(id); entries.get(id)?.resolve(rows.get(id)); }
    } catch (cause) {
      if (stamp !== epoch) return;
      for (const id of scopes) { progressErrors.set(id, cause); entries.get(id)?.resolve(null); }
    } finally {
      if (stamp === epoch) {
        for (const id of scopes) progressPending.delete(id);
        emit();
      }
    }
  }
  return {
    snapshot,
    subscribe(listener) { listeners.add(listener); listener(snapshot()); return () => listeners.delete(listener); },
    setUser(user) {
      const id = user?.id || null;
      if (id === userId) return load();
      userId = id; enabled = !preview && !!id && allowed(id);
      clear(preview ? 'preview' : !id ? 'anonymous' : enabled ? 'loading' : 'disabled'); emit();
      return load();
    },
    setEnabled(value) {
      if (!userId || preview) return;
      enabled = !!value;
      try { storage?.setItem(preferenceKey(userId), enabled ? 'on' : 'off'); } catch { /* Session preference still applies. */ }
      clear(enabled ? 'loading' : 'disabled'); emit();
      return load();
    },
    syncPreference() {
      if (userId && enabled !== allowed(userId)) return this.setEnabled(allowed(userId));
    },
    refresh() { clear(preview ? 'preview' : !userId ? 'anonymous' : enabled ? 'loading' : 'disabled'); emit(); return load(); },
    load,
    getProgress(scopes, {retry = false} = {}) {
      if (phase !== 'ready') return Promise.resolve([]);
      return Promise.all([...new Set(scopes.filter(Boolean))].map(id => {
        if (progress.has(id)) return progress.get(id);
        if (!retry && progressErrors.has(id)) return null;
        if (progressPending.has(id)) return progressPending.get(id).promise;
        let resolve;
        const promise = new Promise(done => { resolve = done; });
        progressPending.set(id, {promise, resolve}); queued.add(id);
        if (!batchScheduled) { batchScheduled = true; queueMicrotask(flushProgress); }
        return promise;
      }));
    }
  };
}

let shared;
export function personalState({preview = false} = {}) {
  if (!shared) {
    let storage;
    try { storage = window.localStorage; } catch { /* Private mode may disable storage. */ }
    shared = createPersonalState({preview, storage, request: learningApi});
  }
  return shared;
}
