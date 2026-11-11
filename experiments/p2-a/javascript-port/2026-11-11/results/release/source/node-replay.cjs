const fs = require('node:fs');
const vm = require('node:vm');
const { isDeepStrictEqual } = require('node:util');

const task = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const context = vm.createContext(Object.create(null), { codeGeneration: { strings: false, wasm: false } });
function close(a, b) {
  return typeof a === 'number' && typeof b === 'number' && Number.isFinite(a) && Number.isFinite(b)
    && Math.abs(a - b) <= 1e-6 + 1e-7 * Math.abs(b);
}
function matches(a, b, tolerance) {
  if (a === b || isDeepStrictEqual(a, b)) return true;
  if (!tolerance) return false;
  if (Array.isArray(b)) return Array.isArray(a) && a.length === b.length && b.every((value,i) => close(a[i],value));
  return close(a,b);
}
const result = { taskId: task.taskId, passed: 0, total: task.cases.length, error: null, failures: [] };
const start = Date.now();
try {
  const code = fs.readFileSync(process.argv[3], 'utf8') + '\n' + fs.readFileSync(process.argv[4], 'utf8');
  vm.runInContext(code, context, { timeout: 2000 });
  const solve = vm.runInContext('solve', context);
  if (typeof solve !== 'function') throw new Error('solve is not callable');
  for (let index = 0; index < task.cases.length; index++) {
    const entry = task.cases[index];
    try {
      const actual = solve(...vm.runInContext(`(${entry.args})`, context));
      const expected = vm.runInContext(`(${entry.expected})`, context);
      if (matches(actual, expected, entry.publicFloatTolerance)) result.passed++;
      else {
        const preview = typeof actual === 'string' ? actual.slice(0,180) : JSON.stringify(actual, (_,x)=>typeof x === 'bigint' ? x.toString()+'n' : x)?.slice(0,180);
        result.failures.push({ index, actual: preview ?? String(actual), error: null });
      }
    } catch (error) {
      result.failures.push({ index, error: String(error).slice(0,180) });
    }
  }
} catch (error) {
  result.error = String(error).slice(0,300);
}
result.durationMs = Date.now() - start;
console.log(JSON.stringify(result));
