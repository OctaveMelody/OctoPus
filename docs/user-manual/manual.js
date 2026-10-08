(() => {
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const controls = document.querySelector('.history-controls');
  const backButton = controls?.querySelector('[data-history="back"]');
  const forwardButton = controls?.querySelector('[data-history="forward"]');
  const homeButton = controls?.querySelector('[data-navigation="home"]');
  const topButton = controls?.querySelector('[data-scroll="top"]');
  const bottomButton = controls?.querySelector('[data-scroll="bottom"]');

  function updateHistoryLabels(language = document.documentElement.lang) {
    const chinese = language === 'zh-CN';
    if (controls) controls.setAttribute('aria-label', chinese ? '手册导航' : 'Manual navigation');
    if (backButton) {
      backButton.textContent = '←';
      backButton.setAttribute('aria-label', chinese ? '后退' : 'Go back');
      backButton.title = chinese ? '后退' : 'Go back';
    }
    if (forwardButton) {
      forwardButton.textContent = '→';
      forwardButton.setAttribute('aria-label', chinese ? '前进' : 'Go forward');
      forwardButton.title = chinese ? '前进' : 'Go forward';
    }
    if (homeButton) {
      homeButton.textContent = '⌂';
      homeButton.setAttribute('aria-label', chinese ? '返回手册首页' : 'Go to manual home');
      homeButton.title = chinese ? '返回手册首页' : 'Go to manual home';
    }
    if (topButton) {
      topButton.textContent = '↑';
      topButton.setAttribute('aria-label', chinese ? '转到页面顶部' : 'Go to page top');
      topButton.title = chinese ? '转到页面顶部' : 'Go to page top';
    }
    if (bottomButton) {
      bottomButton.textContent = '↓';
      bottomButton.setAttribute('aria-label', chinese ? '转到页面底部' : 'Go to page bottom');
      bottomButton.title = chinese ? '转到页面底部' : 'Go to page bottom';
    }
  }

  function select(language, updateHash = false) {
    const selected = language === 'zh-CN' ? 'zh-CN' : 'en';
    if (tabs.length) document.documentElement.lang = selected;
    updateHistoryLabels(selected);
    for (const tab of tabs) {
      const active = tab.id === `tab-${selected}`;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
    }
    if (updateHash) history.replaceState(null, '', `#${selected}`);
  }
  function fromHash() {
    if (!tabs.length) return;
    const fragment = location.hash.slice(1);
    select(fragment.startsWith('zh-CN') ? 'zh-CN' : 'en');
  }
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener('click', () => select(tab.id.slice(4), true));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      tabs[next].focus();
      select(tabs[next].id.slice(4), true);
    });
  }
  window.addEventListener('hashchange', fromHash);
  fromHash();

  backButton?.addEventListener('click', () => history.back());
  forwardButton?.addEventListener('click', () => history.forward());
  homeButton?.addEventListener('click', () => {
    const language = document.documentElement.lang === 'zh-CN' ? 'zh-CN' : 'en';
    const home = new URL('index.html', location.href);
    home.hash = language;
    if (home.href === location.href) {
      select(language, true);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
      location.assign(home.href);
    }
  });
  topButton?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  bottomButton?.addEventListener('click', () => window.scrollTo({
    top: document.documentElement.scrollHeight,
    behavior: 'smooth',
  }));
  updateHistoryLabels();

  const invoke = window.__TAURI__?.core?.invoke;
  if (invoke) {
    document.addEventListener('click', event => {
      const link = event.target instanceof Element ? event.target.closest('.pdf-download a[download]') : null;
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const language = link.href.includes('-zh-CN.pdf') ? 'zh-CN' : 'en';
      invoke('save_user_manual_pdf', { language }).catch(error => {
        alert(language === 'zh-CN' ? `无法保存用户手册 PDF：${error}` : `Could not save the user manual PDF: ${error}`);
      });
    });
  }
})();
