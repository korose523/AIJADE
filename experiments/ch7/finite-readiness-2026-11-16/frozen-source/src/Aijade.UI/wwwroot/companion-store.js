// Media notebooks live in IndexedDB, not the much smaller settings/localStorage quota.
let database;
function open() {
    return database ??= new Promise((resolve, reject) => {
        const request = indexedDB.open("aijade-companion", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("notebooks");
        request.onerror = () => { database = null; reject(request.error); };
        request.onsuccess = () => {
            const db = request.result;
            db.onversionchange = () => { db.close(); database = null; };
            resolve(db);
        };
    });
}
async function transaction(key, mode, value) {
    const db = await open();
    return new Promise((resolve, reject) => {
        const tx = db.transaction("notebooks", mode === "get" ? "readonly" : "readwrite");
        const store = tx.objectStore("notebooks");
        const request = mode === "get" ? store.get(key) : mode === "put" ? store.put(value, key) : store.delete(key);
        tx.oncomplete = () => resolve(mode === "get" ? request.result ?? null : null);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error ?? new Error("The companion notebook could not be saved"));
    });
}
export async function get(key) {
    const value = await transaction(key, "get");
    if (value !== null) return value;
    const legacy = localStorage.getItem(key);
    if (legacy !== null) {
        await transaction(key, "put", legacy);
        localStorage.removeItem(key);
    }
    return legacy;
}
export async function set(key, value) { await transaction(key, "put", value); }
export async function remove(key) { await transaction(key, "delete"); localStorage.removeItem(key); }
