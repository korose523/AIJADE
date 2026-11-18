// This factory can be evaluated directly in a page. Its own monotonic clock owns the window.
export function createBrowserSoakClock(capture, {
    now = () => performance.now(),
    register = (callback, milliseconds) => setInterval(callback, milliseconds),
    cancel = timer => clearInterval(timer),
    intervalMilliseconds = 10_000,
} = {}) {
    let startedAt;
    let stoppedAt;
    let minimumMilliseconds;
    let timer;
    const samples = [];

    function sample(at) {
        return { ...capture(), elapsedSeconds: (at - startedAt) / 1_000 };
    }

    function status() {
        if (startedAt === undefined) throw Error('the browser observation has not started');
        const elapsedMilliseconds = (stoppedAt ?? now()) - startedAt;
        return {
            elapsedSeconds: elapsedMilliseconds / 1_000,
            remainingMilliseconds: Math.max(0, minimumMilliseconds - elapsedMilliseconds),
            mayStop: elapsedMilliseconds >= minimumMilliseconds,
        };
    }

    function start(seconds) {
        if (startedAt !== undefined) throw Error('duplicate browser observation');
        if (!Number.isFinite(seconds) || seconds <= 0) throw Error('invalid browser observation duration');
        minimumMilliseconds = seconds * 1_000;
        startedAt = now();
        samples.push(sample(startedAt));
        timer = register(() => samples.push(sample(now())), intervalMilliseconds);
        return status();
    }

    function stop() {
        if (startedAt === undefined || stoppedAt !== undefined) throw Error('no running browser observation');
        const at = now();
        if (at - startedAt < minimumMilliseconds) throw Error('predeclared browser-clock duration has not elapsed');
        stoppedAt = at;
        cancel(timer);
        // The terminal endpoint can fall immediately after a periodic sample, so keep it out of the interval census.
        return { clock: 'browser.performance.now', startedAt, stoppedAt, minimumMilliseconds, ...status(),
            first: samples[0], last: sample(stoppedAt), samples: [...samples] };
    }

    return { start, status, stop, samples: () => [...samples] };
}
