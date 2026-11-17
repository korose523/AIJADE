"""AIJADE's explicitly versioned, fully measured MacMonitor implementation.

The historical MacMonitor stays unchanged. This subclass runs real samplers,
validators and writers; it does not project or share a previously granted PASS.
The terminal record closes the provisional diagnostic flush measurements.
"""
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from finite_runtime import MacMonitor, require
from process_lifecycle import project_path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class MeasuredMacMonitor(MacMonitor):
    def __init__(self, *args, diagnostic_path, maximum_service_seconds=2, **kwargs):
        require(type(maximum_service_seconds) in (int, float)
                and maximum_service_seconds == 2, 'measured service budget is fixed at two seconds')
        super().__init__(*args, **kwargs)
        self.diagnostic_path = Path(diagnostic_path)
        project_path(self.path)
        project_path(self.diagnostic_path)
        if self.timers_path is not None:
            project_path(self.timers_path)
        self.maximum_service_seconds = maximum_service_seconds
        self.schedule_origin = None
        self.stop_requested_monotonic = None
        self.joined_monotonic = None
        self.services = []
        self._state_mutex = threading.Lock()
        self._terminal = None

    def _run(self):
        self.schedule_origin = time.monotonic()
        deadline = self.schedule_origin
        previous = self.previous_sample_monotonic
        slot = 0
        try:
            with ExitStack() as stack:
                log = stack.enter_context(self.path.open('x'))
                diagnostic = stack.enter_context(self.diagnostic_path.open('x'))
                while True:
                    with self._state_mutex:
                        if self.stop_event.is_set():
                            break
                        began = time.monotonic()
                    row = dict(schema='aijade.mac.monitor-service.v1', slotIndex=slot,
                        scheduledMonotonic=deadline, sampleStartedMonotonic=began,
                        startLatenessSeconds=began-deadline, samplerCompletedMonotonic=None,
                        rawWriterStartedMonotonic=None, rawWriterCompletedMonotonic=None,
                        validatorStartedMonotonic=None, validatorCompletedMonotonic=None,
                        resourcesCompletedMonotonic=None, observationSampleId=None,
                        error=None)
                    try:
                        item = self.sampler()
                        sampled = time.monotonic()
                        row.update(samplerCompletedMonotonic=sampled,
                            observationSampleId=item.get('processObservation', {}).get('sampleId'))
                        item.update(monotonicSeconds=began, sequenceElapsedSeconds=began-self.epoch,
                            elapsedSeconds=began-self.local_epoch, observationCompletedMonotonic=sampled,
                            monitorSlotIndex=slot, monitorScheduledMonotonic=deadline)
                        item['swapIncreaseBytes'] = max(0, item['swapUsedBytes']-self.swap_baseline)
                        self.samples.append(item)
                        row['rawWriterStartedMonotonic'] = time.monotonic()
                        log.write(json.dumps(item, allow_nan=False)+'\n')
                        log.flush()
                        row['rawWriterCompletedMonotonic'] = time.monotonic()
                        require(previous is None or 0 < began-previous <= 3,
                                'runtime process observation coverage gap')
                        row['validatorStartedMonotonic'] = time.monotonic()
                        self.validator(item)
                        row['validatorCompletedMonotonic'] = time.monotonic()
                        require(began-self.epoch <= self.maximum_wall, 'overall wall limit stop')
                        for name, crossed in [('rss', item['rssBytes'] > 2*1024**3),
                                ('available', item['availableBytes'] < 3*1024**3),
                                ('swap', item['swapIncreaseBytes'] > 1024**3)]:
                            if not crossed:
                                self.timers.pop(name, None)
                            else:
                                self.timers.setdefault(name, began)
                                require(began-self.timers[name] < 30, 'runtime sustained '+name+' stop')
                        if self.timers_path:
                            self.timers_path.write_text(json.dumps(self.timers)+'\n')
                        row['resourcesCompletedMonotonic'] = time.monotonic()
                    except BaseException as error:
                        row['error'] = type(error).__name__+': '+str(error)
                        self.errors.append(row['error'])
                        log.write(json.dumps(dict(utc=None, monotonicSeconds=began,
                            sequenceElapsedSeconds=began-self.epoch,
                            monitorSlotIndex=slot, observationError=row['error']))+'\n')
                        log.flush()
                    row['diagnosticWriterStartedMonotonic'] = time.monotonic()
                    raw = canonical(row)+b'\n'
                    diagnostic.write(raw.decode())
                    diagnostic.flush()
                    row['diagnosticRecordSha256'] = hashlib.sha256(raw).hexdigest()
                    with self._state_mutex:
                        self.services.append(row)
                        finished = time.monotonic()
                        row.update(diagnosticWriterCompletedMonotonic=finished,
                            serviceCompletedMonotonic=finished, fullServiceSeconds=finished-began)
                    if not 0 <= row['startLatenessSeconds'] <= .5:
                        self.errors.append('measured monitor start lateness exceeded 0.5 seconds')
                    if row['fullServiceSeconds'] > self.maximum_service_seconds:
                        self.errors.append('complete measured monitor service exceeded two seconds')
                    previous = began
                    slot += 1
                    deadline = self.schedule_origin+2*slot
                    if self.stop_event.wait(max(0, deadline-time.monotonic())):
                        break
        except BaseException as error:
            self.errors.append(type(error).__name__+': '+str(error))

    def stop(self):
        with self._state_mutex:
            if self.stop_requested_monotonic is None:
                self.stop_requested_monotonic = time.monotonic()
            self.stop_event.set()
        self.thread.join(timeout=3)
        if self.joined_monotonic is None:
            self.joined_monotonic = time.monotonic()
        alive = self.thread.is_alive()
        if self._terminal is None:
            expected = (math.ceil(max(0, self.stop_requested_monotonic-self.schedule_origin)/2)
                        if self.schedule_origin is not None else None)
            closure = (expected is not None and expected > 0
                       and [r['slotIndex'] for r in self.services] == list(range(expected)))
            if not closure:
                self.errors.append('measured monitor fixed slot population incomplete')
            if alive:
                self.errors.append('owned observer thread failed to stop')
            self._terminal = dict(schema='aijade.mac.monitor-terminal.v1',
                status='REFUSED_MEASURED_MONITOR' if self.errors else 'COMPLETE_MEASURED_MONITOR_SERVICES',
                scheduleOriginMonotonic=self.schedule_origin, epochMonotonic=self.epoch,
                localEpochMonotonic=self.local_epoch,
                stopRequestedMonotonic=self.stop_requested_monotonic,
                joinedMonotonic=self.joined_monotonic, threadAlive=alive,
                expectedSlotCount=expected, actualSlotCount=len(self.services),
                sampleCount=len(self.samples), fullSlotPopulation=closure,
                maximumServiceSeconds=self.maximum_service_seconds,
                errors=list(self.errors), services=list(self.services),
                diagnosticPath=str(self.diagnostic_path),
                scope='Actual callbacks include raw flush, validator, resources/timers and diagnostic flush; terminal writing occurs after join, outside per-slot service.')
            with self.diagnostic_path.with_suffix('.terminal.json').open('x') as stream:
                json.dump(self._terminal, stream, indent=2, allow_nan=False)
                stream.write('\n')
        require(not alive, 'owned observer thread failed to stop')
        self.check()


def validate_terminal(terminal, raw_records, diagnostic_raw, *, maximum_seconds=600):
    """Cold per-stream check, independent of a producer's claimed PASS."""
    require(terminal.get('schema') == 'aijade.mac.monitor-terminal.v1', 'terminal schema')
    origin = terminal['scheduleOriginMonotonic']
    stop = terminal['stopRequestedMonotonic']
    joined = terminal['joinedMonotonic']
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (origin, stop, joined))
            and 0 < stop-origin <= maximum_seconds and stop <= joined <= stop+3,
            'monitor actual runtime/join envelope')
    require(all(type(terminal[k]) in (int,float) and math.isfinite(terminal[k])
                and 0 <= terminal[k] <= origin for k in ('epochMonotonic','localEpochMonotonic')),
            'monitor original epoch types and envelope')
    expected = math.ceil((stop-origin)/2)
    rows = terminal['services']
    require(all(type(terminal[k]) is int for k in ('expectedSlotCount','actualSlotCount','sampleCount')),
            'monitor count types')
    require(len(rows) == expected == terminal['expectedSlotCount'] == terminal['actualSlotCount']
            == terminal['sampleCount'] == len(raw_records), 'monitor complete fixed slot population')
    require(type(diagnostic_raw) is bytes and diagnostic_raw.endswith(b'\n'), 'diagnostic complete bytes')
    lines = diagnostic_raw.splitlines(keepends=True)
    require(len(lines) == expected, 'diagnostic row population')
    previous = previous_completion = None
    for slot, (row, item, line) in enumerate(zip(rows, raw_records, lines)):
        provisional = json.loads(line)
        require(canonical(provisional)+b'\n' == line, 'canonical complete diagnostic record')
        require(type(row['slotIndex']) is int and type(item['monitorSlotIndex']) is int
                and type(provisional['slotIndex']) is int, 'monitor slot types')
        require(row['slotIndex'] == item['monitorSlotIndex'] == provisional['slotIndex'] == slot,
                'monitor slot order')
        require(row['scheduledMonotonic'] == item['monitorScheduledMonotonic'] == origin+2*slot,
                'monitor immutable deadline schedule')
        start = row['sampleStartedMonotonic']
        require(all(type(row[k]) in (int,float) and math.isfinite(row[k]) for k in
                    ('sampleStartedMonotonic','scheduledMonotonic','startLatenessSeconds'))
                and all(type(item[k]) in (int,float) and math.isfinite(item[k]) for k in
                    ('monotonicSeconds','sequenceElapsedSeconds','elapsedSeconds',
                     'observationCompletedMonotonic','monitorScheduledMonotonic')),
                'monitor raw/derived clock types')
        require(start == item['monotonicSeconds'] and start < stop
                and 0 <= start-row['scheduledMonotonic'] <= .5
                and row['startLatenessSeconds'] == start-row['scheduledMonotonic'],
                'monitor actual start/deadline')
        require(previous is None or 0 < start-previous <= 3, 'monitor coverage gap')
        require(previous_completion is None or previous_completion <= start,
                'same-stream callbacks cannot overlap')
        require(item['sequenceElapsedSeconds'] == start-terminal['epochMonotonic']
                and item['elapsedSeconds'] == start-terminal['localEpochMonotonic'],
                'monitor original epoch elapsed clocks')
        previous = start
        keys = ('sampleStartedMonotonic','samplerCompletedMonotonic','rawWriterStartedMonotonic',
                'rawWriterCompletedMonotonic','validatorStartedMonotonic','validatorCompletedMonotonic',
                'resourcesCompletedMonotonic','diagnosticWriterStartedMonotonic',
                'diagnosticWriterCompletedMonotonic','serviceCompletedMonotonic')
        clocks = [row[k] for k in keys]
        require(all(type(v) in (int,float) and math.isfinite(v) for v in clocks)
                and clocks == sorted(clocks), 'complete monitor service clocks')
        require(row['samplerCompletedMonotonic'] == item['observationCompletedMonotonic'],
                'raw outer sampler clock binding')
        require(row['observationSampleId'] == item['processObservation']['sampleId'],
                'monitor raw observation binding')
        require(row['serviceCompletedMonotonic'] <= joined
                and row['serviceCompletedMonotonic'] == row['diagnosticWriterCompletedMonotonic']
                and row['fullServiceSeconds'] == row['serviceCompletedMonotonic']-start
                and 0 <= row['fullServiceSeconds'] <= 2, 'complete callback service budget')
        previous_completion = row['serviceCompletedMonotonic']
        final_keys = {'diagnosticRecordSha256','diagnosticWriterCompletedMonotonic',
                      'serviceCompletedMonotonic','fullServiceSeconds'}
        require({k:v for k,v in row.items() if k not in final_keys} == provisional
                and row['diagnosticRecordSha256'] == hashlib.sha256(line).hexdigest(),
                'actual flushed diagnostic record binding')
        require(row['error'] is None, 'monitor callback error')
    require(terminal['status'] == 'COMPLETE_MEASURED_MONITOR_SERVICES'
            and terminal['fullSlotPopulation'] is True and terminal['errors'] == []
            and terminal['threadAlive'] is False and terminal['maximumServiceSeconds'] == 2,
            'monitor terminal adverse')
    return dict(status='COMPLETE_MEASURED_MONITOR_STREAM_VALIDATED', samples=expected,
        elapsedSeconds=stop-origin, maximumFullServiceSeconds=max(r['fullServiceSeconds'] for r in rows),
        maximumStartLatenessSeconds=max(r['startLatenessSeconds'] for r in rows))
