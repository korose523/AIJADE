// Background worker: forwards the latest context to the AIJADE server of the signed-in user, if sharing is on.
async function settings() {
  return chrome.storage.local.get({ server: '', token: '', sharing: false });
}

async function send(context) {
  const { server, token, sharing } = await settings();
  if (!sharing || !server || !token) return { ok: false, reason: 'not sharing' };
  const res = await fetch(new URL('api/v1/context/browser', server), {
    method: 'PUT',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
    body: JSON.stringify(context),
  });
  await chrome.storage.local.set({ lastSent: { at: Date.now(), title: context.title, status: res.status } });
  return { ok: res.ok, status: res.status };
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message?.type === 'aijade-context') {
    send(message.context).then(reply, e => reply({ ok: false, reason: String(e) }));
    return true;
  }
  return false;
});
