// Research telemetry on this device (IndexedDB "aijade-research"): sessions keyed by id, turns appended in order. Records
// are stored as the same JSON lines the file store writes, so an export loads directly into pandas / R / DuckDB.
const DB = 'aijade-research';

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      db.createObjectStore('sessions', { keyPath: 'id' });
      db.createObjectStore('turns', { keyPath: 'seq', autoIncrement: true }).createIndex('session', 'sessionId');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run(store, mode, work) {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(store, mode);
      let result;
      Promise.resolve(work(tx.objectStore(store))).then(r => { result = r; });
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

const all = (request) => new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });

export const putSession = (id, json) => run('sessions', 'readwrite', s => { s.put({ id, json }); });
export const addTurn = (sessionId, json) => run('turns', 'readwrite', s => { s.add({ sessionId, json }); });
export const sessions = () => run('sessions', 'readonly', async s => (await all(s.getAll())).map(r => r.json));
export const turns = (sessionId) => run('turns', 'readonly', async s => (await all(s.index('session').getAll(sessionId))).map(r => r.json));
export const allTurns = () => run('turns', 'readonly', async s => (await all(s.getAll())).map(r => r.json));
export async function clear() {
  await run('sessions', 'readwrite', s => { s.clear(); });
  await run('turns', 'readwrite', s => { s.clear(); });
}
