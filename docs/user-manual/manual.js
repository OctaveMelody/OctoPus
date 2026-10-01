(() => {
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function select(language, updateHash = false) {
    const selected = language === 'zh-CN' ? 'zh-CN' : 'en';
    document.documentElement.lang = selected;
    for (const tab of tabs) {
      const active = tab.id === `tab-${selected}`;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
    }
    if (updateHash) history.replaceState(null, '', `#${selected}`);
  }
  function fromHash() {
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
})();
