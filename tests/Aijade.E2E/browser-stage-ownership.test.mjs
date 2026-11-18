import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const origin = new URL('../../src/Aijade.UI/wwwroot/stage.js', import.meta.url);
const dataModule = source => `data:text/javascript,${encodeURIComponent(source)}`;
let importNumber = 0;

function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}

async function fixture(t) {
    const jobs = new Map();
    const canvases = new Map();
    const globals = { window: globalThis.window, document: globalThis.document, aijadeStageTest: globalThis.aijadeStageTest };
    globalThis.window = new EventTarget();
    globalThis.document = {
        getElementById: id => canvases.get(id),
        createElement: () => ({ attached: false, remove() { this.attached = false; } }),
    };
    globalThis.aijadeStageTest = (name, signal) => {
        const job = jobs.get(name);
        job.signal = signal;
        job.start();
        return job.promise;
    };
    const live2dStub = dataModule(`
        export function isLive2DModel(url) { return url.endsWith('.model3.json'); }
        export function installedLive2DModel() { throw new Error('fixture needs an explicit model URL'); }
        export function mountLive2D(canvas, options, signal) { return globalThis.aijadeStageTest(canvas.id, signal); }
    `);
    const mmdStub = dataModule(`
        export const MmdRenderer = { create(surface) { return globalThis.aijadeStageTest(surface.canvas.id); } };
    `);
    const stageSource = await readFile(origin, 'utf8');
    const linked = stageSource.replace("'./live2d-renderer.js'", JSON.stringify(live2dStub))
        .replace("'./mmd-renderer.js'", JSON.stringify(mmdStub));
    const stage = await import(`${dataModule(linked)}#${++importNumber}`);
    t.after(() => {
        stage.unmount();
        Object.assign(globalThis, globals);
    });

    function model(id, kind = 'live2d') {
        const renderer = { kind, releases: 0, diagnostics: { owner: id }, dispose() { this.releases++; } };
        const ready = deferred();
        const started = deferred();
        const job = { start: started.resolve, promise: ready.promise, signal: null };
        const canvas = new EventTarget();
        Object.assign(canvas, { id, hidden: false, before(surface) {
            this.surface = surface;
            surface.canvas = this;
            surface.attached = true;
        } });
        canvases.set(id, canvas);
        jobs.set(id, job);
        return { canvas, renderer, job, started: started.promise, resolve: () => ready.resolve(renderer),
            mount: () => stage.mount(id, { modelUrl: kind === 'live2d' ? `${id}.model3.json` : `${id}.pmx` }) };
    }
    return { stage, model };
}

test('disposing an older mounted panel leaves the new current Live2D stage active', async t => {
    const { stage, model } = await fixture(t);
    const old = model('old');
    const next = model('next');
    old.resolve();
    next.resolve();
    assert.equal((await old.mount()).renderer, 'live2d');
    assert.equal((await next.mount()).renderer, 'live2d');
    stage.unmount('old');
    assert.deepEqual(stage.rendererDiagnostics(), { owner: 'next' });
    assert.equal(old.renderer.releases, 1);
    assert.equal(next.renderer.releases, 0);
    stage.unmount('next');
    stage.unmount('next');
    assert.equal(next.renderer.releases, 1);
});

test('an older disposal cannot cancel a newer pending mount and the late old renderer is released', async t => {
    const { stage, model } = await fixture(t);
    const old = model('old', 'mmd');
    const next = model('next');
    const oldMount = old.mount();
    await old.started;
    assert.equal(old.canvas.hidden, true);
    const nextMount = next.mount();
    await next.started;
    assert.equal(old.canvas.hidden, false);
    assert.equal(old.canvas.surface.attached, false);
    stage.unmount('old');
    next.resolve();
    old.resolve();
    assert.equal((await oldMount).renderer, 'unmounted');
    assert.equal((await nextMount).renderer, 'live2d');
    assert.equal(old.renderer.releases, 1);
    assert.equal(next.job.signal.aborted, false);
    assert.equal(next.renderer.releases, 0);
});

test('its own pending disposal cancels the stage and rejects a late renderer', async t => {
    const { stage, model } = await fixture(t);
    const owner = model('owner');
    const pending = owner.mount();
    await owner.started;
    stage.unmount('owner');
    owner.resolve();
    assert.equal((await pending).renderer, 'unmounted');
    assert.equal(owner.job.signal.aborted, true);
    assert.equal(owner.renderer.releases, 1);
    assert.equal(stage.rendererDiagnostics(), null);
});

test('a mount whose canvas no longer exists leaves the running stage active', async t => {
    const { stage, model } = await fixture(t);
    const current = model('current');
    current.resolve();
    assert.equal((await current.mount()).renderer, 'live2d');
    await assert.rejects(stage.mount('missing', {}), /no canvas #missing/);
    assert.deepEqual(stage.rendererDiagnostics(), { owner: 'current' });
    assert.equal(current.renderer.releases, 0);
});
