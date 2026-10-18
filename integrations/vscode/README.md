# AIJADE for VS Code

Lets your AIJADE companion know what you are working on. Every few seconds it reports the file name, language and line to
your AIJADE server; with **AIJADE: Share code** (`aijade.shareCode`) on, it also sends the selected text or the lines
around the cursor. Nothing is sent before you sign in, while sharing is paused, or for code unless you allow it.

1. Run **AIJADE: Sign in** (it asks for your server address, email and password; the session token is kept in VS Code's
   secret storage).
2. In the AIJADE app, turn on **What I'm working on (VS Code)** under Settings → Modules.

Install from this folder with `code --install-extension` after packaging (`npx @vscode/vsce package`), or run it from
VS Code's extension development host (F5 with this folder open).
