// AIJADE for VS Code: reports the file, language and line in front of you (and code only when aijade.shareCode is on) to
// your AIJADE server, where the companion can use it if "What I'm working on" is enabled in the AIJADE app.
const vscode = require('vscode');
const { describe } = require('./context.js');

const TOKEN_KEY = 'aijade.token';
let timer;
let lastKey = '';
let status;

function settings() {
  const c = vscode.workspace.getConfiguration('aijade');
  return { server: c.get('server'), enabled: c.get('enabled'), shareCode: c.get('shareCode'), contextLines: c.get('contextLines'), interval: c.get('sendInterval') };
}

async function send(secrets) {
  const s = settings();
  const editor = vscode.window.activeTextEditor;
  const token = await secrets.get(TOKEN_KEY);
  if (!s.enabled || !s.server || !token || !editor) return;
  const doc = editor.document;
  const sel = editor.selection;
  const context = describe({
    fileName: doc.fileName,
    languageId: doc.languageId,
    workspace: vscode.workspace.getWorkspaceFolder(doc.uri)?.name,
    line: sel.active.line,
    selection: sel.isEmpty ? '' : doc.getText(sel),
    lines: s.shareCode ? doc.getText().split(/\r?\n/) : [],
  }, s);
  const key = JSON.stringify(context);
  if (key === lastKey) return;
  lastKey = key;
  try {
    const res = await fetch(new URL('api/v1/context/ide', s.server), {
      method: 'PUT', headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` }, body: key,
    });
    status.text = res.ok ? '$(sparkle) AIJADE' : `$(warning) AIJADE ${res.status}`;
  } catch {
    status.text = '$(debug-disconnect) AIJADE';
  }
}

function schedule(secrets) {
  clearInterval(timer);
  timer = setInterval(() => send(secrets), Math.max(1000, settings().interval || 3000));
}

async function activate(context) {
  const secrets = context.secrets;
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = 'aijade.status';
  status.text = '$(sparkle) AIJADE';
  status.show();
  context.subscriptions.push(status,
    vscode.commands.registerCommand('aijade.signIn', async () => {
      let server = settings().server;
      if (!server) {
        server = await vscode.window.showInputBox({ prompt: 'AIJADE server address', placeHolder: 'https://aijade.example/' });
        if (!server) return;
        await vscode.workspace.getConfiguration('aijade').update('server', server, vscode.ConfigurationTarget.Global);
      }
      const email = await vscode.window.showInputBox({ prompt: 'Email' });
      const password = email && await vscode.window.showInputBox({ prompt: 'Password', password: true });
      if (!password) return;
      const res = await fetch(new URL('api/v1/auth/sign-in/email', server), {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return vscode.window.showErrorMessage(`AIJADE sign-in failed: ${body.message || res.status}`);
      await secrets.store(TOKEN_KEY, body.token);
      vscode.window.showInformationMessage('AIJADE: signed in.');
    }),
    vscode.commands.registerCommand('aijade.signOut', async () => {
      await secrets.delete(TOKEN_KEY);
      vscode.window.showInformationMessage('AIJADE: signed out.');
    }),
    vscode.commands.registerCommand('aijade.toggle', async () => {
      const enabled = !settings().enabled;
      await vscode.workspace.getConfiguration('aijade').update('enabled', enabled, vscode.ConfigurationTarget.Global);
      vscode.window.showInformationMessage(`AIJADE: sharing ${enabled ? 'resumed' : 'paused'}.`);
    }),
    vscode.commands.registerCommand('aijade.status', async () => {
      const s = settings();
      vscode.window.showInformationMessage(`AIJADE: ${s.enabled ? 'sharing' : 'paused'} · server ${s.server || 'not set'} · ${await secrets.get(TOKEN_KEY) ? 'signed in' : 'signed out'} · code ${s.shareCode ? 'shared' : 'not shared'}`);
    }),
    vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('aijade')) schedule(secrets); }),
    { dispose: () => clearInterval(timer) });
  schedule(secrets);
}

function deactivate() {
  clearInterval(timer);
}

module.exports = { activate, deactivate };
