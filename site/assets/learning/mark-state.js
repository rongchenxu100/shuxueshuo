// Only the two learning fields live on the server. Pending work lives on this page.
export const emptyMark = () => ({practiced: false, learning_status: 'unmarked'});
export function presentation(mark) {
  if (!mark.practiced) return {label: '未练习', tone: 'new', action: '开始练习'};
  if (mark.learning_status === 'mastered') return {label: '已掌握', tone: 'mastered', action: '查看题目'};
  if (mark.learning_status === 'needs_review') return {label: '需再练', tone: 'review', action: '再练一次'};
  return {label: '待自评', tone: 'pending', action: '标记掌握情况'};
}

export class LearningMark {
  constructor(send, changed) {
    this.send = send; this.changed = changed;
    this.user = null; this.lastUser = null; this.generation = 0;
    this.mark = emptyMark(); this.completedHere = false;
    this.pending = null; this.phase = 'idle'; this.error = '';
  }
  notify() { this.changed(this); }
  async setUser(id, reason = 'refresh') {
    const discard = reason === 'logout' || (id && this.lastUser && id !== this.lastUser);
    if (id === this.user && !discard) return;
    this.generation++;
    this.user = id; this.mark = emptyMark(); this.phase = 'idle'; this.error = '';
    if (discard) { this.completedHere = false; this.pending = null; }
    if (id) this.lastUser = id;
    if (reason === 'logout') this.lastUser = null;
    this.notify();
    if (id) await this.reload();
  }
  complete() {
    if (this.completedHere) return;
    this.completedHere = true;
    if (!this.mark.practiced && !this.pending) this.pending = {kind: 'complete'};
    this.notify();
    void this.flush();
  }
  async reload() {
    if (!this.user || ['loading', 'saving'].includes(this.phase)) return;
    const generation = this.generation, user = this.user;
    this.phase = 'loading'; this.error = ''; this.notify();
    try {
      const mark = await this.send('read', null, user);
      if (generation !== this.generation) return;
      this.mark = mark; this.phase = 'idle';
      if (this.completedHere && !mark.practiced && !this.pending) this.pending = {kind: 'complete'};
      this.notify();
      await this.flush();
    } catch (error) {
      if (generation !== this.generation) return;
      this.phase = 'error'; this.error = error.message; this.notify();
    }
  }
  async choose(status) {
    if (!this.user || !this.mark.practiced || this.pending || ['saving', 'loading'].includes(this.phase)) return;
    this.pending = {kind: 'status', status};
    await this.flush();
  }
  async flush() {
    if (!this.user || !this.pending || ['loading', 'saving'].includes(this.phase)) return;
    const generation = this.generation, user = this.user, operation = this.pending;
    this.phase = 'saving'; this.error = ''; this.notify();
    try {
      const mark = await this.send(operation.kind, operation.status, user);
      if (generation !== this.generation) return;
      this.mark = mark;
      if (this.pending === operation) this.pending = null;
      this.phase = 'idle'; this.notify();
      if (this.pending) await this.flush();
    } catch (error) {
      if (generation !== this.generation) return;
      this.phase = 'error'; this.error = error.message; this.notify();
    }
  }
  async retry() {
    if (this.pending) await this.flush();
    else await this.reload();
  }
}
