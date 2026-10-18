// Content script: every few seconds, report what is on screen to the background worker (only when it changed).
(async () => {
  const { extractContext } = await import(chrome.runtime.getURL('extract.js'));
  let last = '';
  setInterval(() => {
    if (document.visibilityState !== 'visible') return;
    const context = extractContext(document, location);
    const key = JSON.stringify({ ...context, position: undefined });
    if (key === last) return;
    last = key;
    chrome.runtime.sendMessage({ type: 'aijade-context', context }).catch(() => {});
  }, 5000);
})();
