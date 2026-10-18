const $ = (id) => document.getElementById(id);

async function render() {
  const { server, token, sharing, lastSent } = await chrome.storage.local.get({ server: '', token: '', sharing: false, lastSent: null });
  $('signin').hidden = !!token;
  $('connected').hidden = !token;
  $('server').value = server;
  $('where').textContent = server;
  $('sharing').checked = sharing;
  $('last').textContent = lastSent ? `Last shared: "${lastSent.title}" (${new Date(lastSent.at).toLocaleTimeString()}, HTTP ${lastSent.status})` : '';
}

$('signin').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('error').textContent = '';
  const server = new URL($('server').value).origin + '/';
  // The server is the user's own choice: ask for access to exactly that origin.
  if (!await chrome.permissions.request({ origins: [server + '*'] })) {
    $('error').textContent = 'Access to the server was not granted.';
    return;
  }
  try {
    const res = await fetch(new URL('api/v1/auth/sign-in/email', server), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email: $('email').value, password: $('password').value }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
    await chrome.storage.local.set({ server, token: body.token, sharing: false });
    $('password').value = '';
    render();
  } catch (err) {
    $('error').textContent = `Sign-in failed: ${err.message}`;
  }
});

$('sharing').addEventListener('change', async () => {
  await chrome.storage.local.set({ sharing: $('sharing').checked });
  if (!$('sharing').checked) {
    const { server, token } = await chrome.storage.local.get({ server: '', token: '' });
    // Stopping also withdraws what was last shared.
    fetch(new URL('api/v1/context/browser', server), { method: 'DELETE', headers: { authorization: `Bearer ${token}` } }).catch(() => {});
  }
});

$('signout').addEventListener('click', async () => {
  await chrome.storage.local.set({ token: '', sharing: false });
  render();
});

render();
