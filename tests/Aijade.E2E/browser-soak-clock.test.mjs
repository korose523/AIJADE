import assert from 'node:assert/strict';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { createBrowserSoakClock } from './browser-soak-clock.mjs';

function fixture() {
    let milliseconds = 3_200;
    let callback;
    let cancelled = false;
    let captureNumber = 0;
    const clock = createBrowserSoakClock(() => ({ captureNumber: ++captureNumber }), {
        now: () => milliseconds,
        register: next => { callback = next; return 'browser-timer'; },
        cancel: timer => { assert.equal(timer, 'browser-timer'); cancelled = true; },
    });
    return { clock, advance: amount => { milliseconds += amount; }, tick: () => callback(), cancelled: () => cancelled };
}

test('the prior 12.1 ms shortfall cannot stop or cancel an observation', () => {
    const f = fixture();
    f.clock.start(1_800);
    f.advance(1_799_987.9);
    assert.equal(f.clock.status().mayStop, false);
    assert.throws(() => f.clock.stop(), /has not elapsed/);
    assert.equal(f.cancelled(), false);
    f.advance(13);
    assert.equal(f.clock.status().mayStop, true);
    assert.ok(f.clock.stop().elapsedSeconds >= 1_800);
    assert.equal(f.cancelled(), true);
});

test('the exact deadline and endpoint are measured on the sampling clock', () => {
    const f = fixture();
    assert.throws(() => f.clock.status(), /has not started/);
    f.clock.start(1_800);
    assert.throws(() => f.clock.start(1_800), /duplicate/);
    f.advance(10_000);
    f.tick();
    f.advance(1_790_000);
    f.tick();
    const result = f.clock.stop();
    assert.equal(result.stoppedAt - result.startedAt, 1_800_000);
    assert.equal(result.elapsedSeconds, 1_800);
    assert.deepEqual(result.samples.map(x => x.elapsedSeconds), [0, 10, 1_800]);
    assert.deepEqual(result.first, { elapsedSeconds: 0, captureNumber: 1 });
    assert.deepEqual(result.last, { elapsedSeconds: 1_800, captureNumber: 4 });
    f.advance(15);
    assert.equal(f.clock.status().elapsedSeconds, 1_800);
    assert.throws(() => f.clock.stop(), /no running/);
});

test('the exact factory source evaluates with page-local timing globals', () => {
    let now = 50;
    const page = runInNewContext(`(${createBrowserSoakClock.toString()})(() => ({visible: true}))`, {
        performance: { now: () => now }, setInterval: () => 26, clearInterval: id => assert.equal(id, 26),
    });
    page.start(1);
    now += 1_001;
    const result = page.stop();
    assert.equal(result.elapsedSeconds, 1.001);
    assert.equal(result.last.visible, true);
});
