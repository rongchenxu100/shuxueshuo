/* Shared phone login. Credentials live in HttpOnly cookies, never in JS storage. */
(() => {
  'use strict';
  if (window.SiteAuth || window.self !== window.top) return;
  let user = null, enabled = false, reachable = false, epoch = 0, busy = false, challenge = null, retryAt = 0;
  let refreshPending = false, toastTimer = 0;
  let dialog, host, trigger, menu, menuPhone, menuNote, logout, phone, code, send, submit, message, toast;
  const listeners = new Set();
  const scriptURL = new URL(document.currentScript?.src || import.meta.url);
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = new URL(`site-auth.css${scriptURL.search}`, scriptURL).href;
  document.head.append(css);

  const USER_ICON = '<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><circle cx="10" cy="7" r="3.4" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3.6 17c.9-3.2 3.4-4.8 6.4-4.8s5.5 1.6 6.4 4.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  async function api(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 22000);
    try {
      const response = await fetch(`/api/auth/${path}`, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: body === undefined ? {} : {'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      });
      const data = response.status === 204 ? {} : await response.json();
      if (!response.ok) {
        const failure = new Error(typeof data.detail === 'string' ? data.detail : '暂时无法完成，请稍后重试。');
        failure.retryAfter = Number(response.headers.get('Retry-After')) || 0;
        throw failure;
      }
      return data;
    } catch (failure) {
      if (failure.name === 'AbortError' || failure instanceof TypeError || failure instanceof SyntaxError) {
        throw new Error('暂时无法连接登录服务，请稍后重试。');
      }
      throw failure;
    } finally { clearTimeout(timer); }
  }

  function render() {
    // Without a confirmed auth service there is nothing useful to click; a known
    // account stays visible through transient failures so it is not mistaken for logout.
    host.hidden = !(enabled && (reachable || user));
    host.classList.toggle('is-signed-in', Boolean(user));
    trigger.setAttribute('aria-haspopup', user ? 'menu' : 'dialog');
    trigger.setAttribute('aria-label', user ? `账号 ${user.phone}` : '登录');
    trigger.querySelector('.sss-account-text').textContent = user ? `尾号 ${user.phone.slice(-4)}` : '登录';
    menuPhone.textContent = user ? user.phone : '';
    menuNote.textContent = reachable ? '' : '登录状态暂时无法确认';
    if (!user) closeMenu();
  }

  function publish(next) {
    user = next;
    render();
    for (const listener of listeners) listener(user);
    window.dispatchEvent(new CustomEvent('site-auth-change', {detail: {user}}));
  }

  function broadcast() {
    // A timestamp only: never persist user details, tokens or verification codes.
    try { localStorage.setItem('sss-auth-change', String(Date.now())); } catch { /* Storage may be disabled. */ }
  }

  function notify(text) {
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 2400);
  }

  async function refresh() {
    if (busy) { refreshPending = true; return; }
    const ticket = ++epoch;
    try {
      const data = await api('me');
      if (ticket !== epoch) return;
      enabled = data.enabled; reachable = true;
      publish(data.user);
      if (user && dialog.open) dialog.close();
    } catch {
      if (ticket !== epoch) return;
      // A transient network failure is not a logout; keep current practice intact.
      reachable = false;
      render();
    }
  }

  function settle(ticket) {
    busy = false;
    renderControls();
    if (ticket !== epoch || refreshPending) { refreshPending = false; refresh(); }
  }

  function say(text, tone = 'info') {
    message.textContent = text;
    message.dataset.tone = tone;
  }

  function renderControls() {
    const seconds = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
    if (!send.classList.contains('is-sending')) send.textContent = seconds ? `重新发送 ${seconds}s` : (challenge ? '重新发送' : '获取验证码');
    send.disabled = busy || seconds > 0 || !/^1[3-9]\d{9}$/.test(phone.value);
    submit.disabled = busy || !challenge || code.value.length !== 6;
    phone.disabled = busy;
    code.disabled = busy || !challenge;
    logout.disabled = busy;
    dialog.setAttribute('aria-busy', String(busy));
  }

  function open() {
    if (user) return;
    say('');
    closeMenu();
    if (!dialog.open) dialog.showModal();
    (challenge ? code : phone).focus();
  }

  function openMenu() {
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    logout.focus();
  }

  function closeMenu(restoreFocus) {
    if (menu.hidden) return;
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus) trigger.focus();
  }

  function mount() {
    host = document.createElement('div');
    host.className = 'sss-account';
    host.hidden = true;
    host.innerHTML = `<button type="button" class="sss-account-trigger" aria-expanded="false">${USER_ICON}<span class="sss-account-text">登录</span></button>
      <div class="sss-account-menu" role="menu" hidden>
        <p class="sss-account-who"><small>已登录</small><b class="sss-account-phone"></b><span class="sss-account-note"></span></p>
        <button type="button" class="sss-account-logout" role="menuitem">退出登录</button>
      </div>`;
    const anchor = document.querySelector('[data-site-auth], .home-v2-nav, .topbar-inner, .lesson-topbar, .site-nav');
    if (anchor) anchor.append(host);
    else { host.classList.add('sss-account-floating'); document.body.append(host); }
    trigger = host.querySelector('.sss-account-trigger');
    menu = host.querySelector('.sss-account-menu');
    menuPhone = host.querySelector('.sss-account-phone');
    menuNote = host.querySelector('.sss-account-note');
    logout = host.querySelector('.sss-account-logout');

    dialog = document.createElement('dialog');
    dialog.className = 'sss-auth-dialog';
    dialog.setAttribute('aria-labelledby', 'sss-auth-title');
    dialog.innerHTML = `<div class="sss-auth-inner">
      <header class="sss-auth-head">
        <h2 id="sss-auth-title">手机号登录</h2>
        <button type="button" class="sss-auth-close" aria-label="关闭登录"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
      </header>
      <p class="sss-auth-intro">验证手机号即可登录，未注册的手机号会自动创建账号。</p>
      <form class="sss-auth-form" novalidate>
        <label class="sss-auth-label" for="sss-auth-phone">手机号</label>
        <div class="sss-auth-field"><span class="sss-auth-prefix" aria-hidden="true">+86</span><input id="sss-auth-phone" name="phone" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="11" placeholder="11 位手机号" required></div>
        <label class="sss-auth-label" for="sss-auth-code">短信验证码</label>
        <div class="sss-auth-code-row"><div class="sss-auth-field"><input id="sss-auth-code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6 位数字" required></div><button type="button" class="sss-auth-send">获取验证码</button></div>
        <p class="sss-auth-message" role="status" aria-live="polite"></p>
        <button type="submit" class="sss-auth-submit" disabled>登录</button>
      </form>
    </div>`;
    document.body.append(dialog);
    toast = document.createElement('div');
    toast.className = 'sss-auth-toast';
    toast.setAttribute('role', 'status');
    toast.hidden = true;
    document.body.append(toast);
    phone = dialog.querySelector('#sss-auth-phone'); code = dialog.querySelector('#sss-auth-code');
    send = dialog.querySelector('.sss-auth-send'); submit = dialog.querySelector('.sss-auth-submit');
    message = dialog.querySelector('.sss-auth-message');

    trigger.addEventListener('click', () => {
      if (!user) open();
      else if (menu.hidden) openMenu();
      else closeMenu(true);
    });
    menu.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(true); });
    document.addEventListener('click', event => { if (!host.contains(event.target)) closeMenu(); });
    host.addEventListener('focusout', event => { if (!host.contains(event.relatedTarget)) closeMenu(); });
    dialog.querySelector('.sss-auth-close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { code.value = ''; renderControls(); });
    phone.addEventListener('input', () => {
      phone.value = phone.value.replace(/\D/g, '').slice(0, 11);
      if (challenge && challenge.phone !== phone.value) { challenge = null; code.value = ''; say(''); }
      renderControls();
    });
    code.addEventListener('input', () => {
      code.value = code.value.replace(/\D/g, '').slice(0, 6);
      renderControls();
    });
    send.addEventListener('click', async () => {
      if (busy || retryAt > Date.now()) return;
      if (!/^1[3-9]\d{9}$/.test(phone.value)) { say('请输入 11 位手机号。', 'error'); phone.focus(); return; }
      busy = true; say(''); send.classList.add('is-sending'); send.textContent = '发送中…'; renderControls();
      const ticket = ++epoch, number = phone.value;
      try {
        const data = await api('sms/send', {phone: number});
        if (ticket !== epoch) return;
        challenge = {id: data.challenge_id, phone: number};
        retryAt = Date.now() + data.retry_after * 1000;
        say(`验证码已发送至 ${number.slice(0, 3)}****${number.slice(-4)}，5 分钟内有效。`, 'success');
      } catch (failure) {
        if (ticket !== epoch) return;
        say(failure.message, 'error');
        if (failure.retryAfter) retryAt = Date.now() + failure.retryAfter * 1000;
      } finally {
        send.classList.remove('is-sending');
        settle(ticket);
        if (dialog.open && challenge) code.focus();
      }
    });
    dialog.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !challenge || code.value.length !== 6) return;
      busy = true; say(''); submit.textContent = '登录中…'; renderControls();
      const ticket = ++epoch;
      try {
        const data = await api('sms/verify', {phone: challenge.phone, challenge_id: challenge.id, code: code.value});
        if (ticket !== epoch) return;
        reachable = true; challenge = null; retryAt = 0;
        publish(data.user); broadcast(); dialog.close();
        notify('登录成功');
      } catch (failure) {
        if (ticket === epoch) { say(failure.message, 'error'); code.select(); }
      } finally { submit.textContent = '登录'; settle(ticket); }
    });
    logout.addEventListener('click', async () => {
      if (busy) return;
      busy = true; const ticket = ++epoch; renderControls(); menuNote.textContent = '';
      try {
        await api('logout', {});
        if (ticket !== epoch) return;
        challenge = null; code.value = ''; closeMenu(); publish(null); broadcast();
        notify('已退出登录');
      } catch (failure) { if (ticket === epoch) menuNote.textContent = failure.message; }
      finally { settle(ticket); }
    });
    setInterval(() => { if (dialog.open) renderControls(); }, 1000);
    window.addEventListener('storage', event => { if (event.key === 'sss-auth-change') refresh(); });
    window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    render();
    renderControls();
    refresh();
  }

  window.SiteAuth = {open, refresh, get user() { return user; }, get enabled() { return enabled; },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
