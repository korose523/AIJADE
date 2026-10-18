// What is being worked on, from plain editor facts (no vscode import, so it can be tested on its own).
function describe(editor, options) {
  const { fileName, languageId, workspace, line, selection, lines } = editor;
  const shown = (name) => name.split(/[\\/]/).pop();
  const context = { site: workspace || 'VS Code', kind: 'code', title: `${shown(fileName)} (${languageId})`, position: `line ${line + 1}` };
  if (options.shareCode) {
    if (selection && selection.trim()) {
      context.text = selection.slice(0, 2000);
    } else if (lines && lines.length) {
      const from = Math.max(0, line - options.contextLines);
      const to = Math.min(lines.length, line + options.contextLines + 1);
      context.text = lines.slice(from, to).join('\n').slice(0, 2000);
    }
  }
  return context;
}

module.exports = { describe };
