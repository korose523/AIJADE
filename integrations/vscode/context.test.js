// Run with: node --test integrations/vscode/context.test.js
const test = require('node:test');
const assert = require('node:assert');
const { describe } = require('./context.js');

test('without shareCode only the file, language and line leave the machine', () => {
  const c = describe({ fileName: 'C:\\work\\Program.cs', languageId: 'csharp', workspace: 'work', line: 0, selection: 'password = "x"', lines: ['secret'] }, { shareCode: false, contextLines: 5 });
  assert.deepStrictEqual(c, { site: 'work', kind: 'code', title: 'Program.cs (csharp)', position: 'line 1' });
});

test('with shareCode the selection wins, else the lines around the cursor', () => {
  const lines = ['a', 'b', 'c', 'd', 'e'];
  assert.strictEqual(describe({ fileName: '/w/app.ts', languageId: 'typescript', line: 2, selection: 'sel', lines }, { shareCode: true, contextLines: 1 }).text, 'sel');
  assert.strictEqual(describe({ fileName: '/w/app.ts', languageId: 'typescript', line: 2, selection: '', lines }, { shareCode: true, contextLines: 1 }).text, 'b\nc\nd');
  assert.strictEqual(describe({ fileName: '/w/app.ts', languageId: 'typescript', line: 0, selection: '', lines }, { shareCode: true, contextLines: 1 }).text, 'a\nb');
});
