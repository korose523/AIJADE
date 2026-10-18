# AIJADE for Claude Code

Talk with your AIJADE companion from Claude Code, and let Claude search what you have told the companion.

The plugin connects Claude Code to the AIJADE server's MCP endpoint (`/mcp`), which offers three tools that act as your
account: `companion_chat` (talk with the companion; the conversation continues in your "MCP" chat), `memory_search` and
`memory_remember` (your long-term memory, through the same gated pipeline as chat).

## Setup

1. Get a token for your account: sign in to the AIJADE web app and copy the session token, or have the server's admin add
   a static token (`Auth:StaticTokens:<token>=<your user id>`).
2. Set the environment before starting Claude Code:

   ```bash
   export AIJADE_URL=https://your-aijade-server.example
   export AIJADE_TOKEN=<token>
   ```

3. Install the plugin from this folder, e.g. `claude --plugin-dir integrations/claude-code`, or add the repository as a
   marketplace.

Then `/aijade How was your day?` asks the companion, and Claude can call `memory_search` when your memory would help.

Unlike the earlier plugin, nothing you type in Claude Code is forwarded to the companion unless you use the command or
Claude calls a tool, so development work does not end up in the companion's memory by accident.
