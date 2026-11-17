#!/usr/bin/env python3
"""Versioned, streaming fixed preflight; no observer, file, process or network I/O.

Callers open durable raw/event writers before entering this controller.  A raw
sample cannot contain its own write-completion timestamp: that actual timestamp
is recorded in the subsequent, identity-bound ``sample-written`` event instead.
Independent post-execution replay remains mandatory.
"""
import math
import time


EVENT_SCHEMA = 'aijade.ch7.phase-continuity-event.v1'
RESULT_SCHEMA = 'aijade.ch7.phase-continuity-preflight.v1'
INTERVAL_SECONDS = 2
MAX_GAP_SECONDS = 3
GIB = 1024 ** 3


class PreflightRefused(ValueError):
    """A terminal refusal, including the partial state; never a retry request."""

    def __init__(self, code, message, result):
        self.code = code
        self.result = result
        super().__init__(code + ': ' + message)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class _Controller:
    def __init__(self, sampler, validator, writers, event_writer, settling_seconds,
                 clock, sleeper, service_observer=None):
        if settling_seconds not in (0, 600) or type(settling_seconds) is not int:
            raise ValueError('settling_seconds must be exactly 0 or 600')
        self.specs = ([('settling', 600, 300)] if settling_seconds else []) + [('admission', 120, 60)]
        if not callable(sampler) or not callable(validator) or not callable(event_writer):
            raise ValueError('sampler, validator and prepared event_writer are required')
        if type(writers) is not dict or any(not callable(writers.get(name)) for name, _, _ in self.specs):
            raise ValueError('each phase requires a prepared raw writer')
        self.sampler, self.validator = sampler, validator
        self.writers, self.event_writer = writers, event_writer
        self.clock, self.sleeper = clock, sleeper
        self.service_observer = service_observer
        self.last_clock = None
        self.previous = None
        self.sample_ids = set()
        self.phase = None
        self.result = dict(schema=RESULT_SCHEMA, status='PREFLIGHT_RUNNING',
                           phases={}, eventCount=0, samples=0, validatedSamples=0,
                           maximumGlobalGapSeconds=0, lastSample=None,
                           runtimeHandoffAnchor=None, windowReset=False)

    def now(self):
        value = self.clock()
        if not _number(value) or (self.last_clock is not None and value < self.last_clock):
            self.fail('CLOCK_REVERSED_OR_INVALID', 'monotonic clock is invalid or reversed')
        self.last_clock = value
        return value

    def event(self, kind, point, **fields):
        record = dict(schema=EVENT_SCHEMA, eventIndex=self.result['eventCount'],
                      event=kind, monotonicSeconds=point, **fields)
        self.event_writer(record)
        self.result['eventCount'] += 1

    def fail(self, code, message):
        self.result.update(status='PREFLIGHT_REFUSED', reasonCode=code, reason=message,
                           refusedAtMonotonic=self.last_clock)
        if self.phase is not None:
            self.phase['status'] = 'PREFLIGHT_REFUSED'
            self.phase['coverage']['coverageComplete'] = False
        raise PreflightRefused(code, message, self.result)

    def wait_until(self, target):
        now = self.now()
        if now < target:
            self.sleeper(target - now)
            now = self.now()
            if now < target:
                self.fail('EARLY_SLEEP_RETURN', 'sleep returned before the absolute deadline')
        return now

    def begin(self, name, duration, count, start):
        self.phase = dict(status='FIXED_PHASE_RUNNING', samples=0, validatedSamples=0,
                          expectedSamples=count, elapsedSeconds=None,
                          minimumAvailableBytes=None, minimumSwapUsedBytes=None,
                          maximumSwapUsedBytes=None, swapRangeBytes=None,
                          phaseClock=dict(startMonotonic=start, endMonotonic=None,
                                          requestedSeconds=duration, intervalReset=False),
                          coverage=dict(samples=0, maximumGapSeconds=0,
                                        firstElapsedSeconds=None, lastElapsedSeconds=None,
                                        coverageComplete=False))
        self.result['phases'][name] = self.phase
        self.phase_previous = None
        return start + duration

    def observe(self, name, local_index, global_index, target, deadline):
        start = self.wait_until(target)
        if start >= deadline:
            self.fail('SAMPLE_DEADLINE_MISSED', 'a required sample did not start inside its fixed phase')
        if self.previous is not None:
            gap = start - self.previous['monotonicSeconds']
            if not 0 < gap <= MAX_GAP_SECONDS:
                self.fail('SAMPLE_GAP', 'adjacent actual sample starts are reversed or more than three seconds apart')
            self.result['maximumGlobalGapSeconds'] = max(self.result['maximumGlobalGapSeconds'], gap)
        elif start - self.phase['phaseClock']['startMonotonic'] > MAX_GAP_SECONDS:
            self.fail('FIRST_SAMPLE_GAP', 'the first actual sample is missing at the fixed phase origin')

        captured = self.sampler()
        completed = self.now()
        if type(captured) is not dict:
            self.fail('INVALID_SAMPLE', 'sampler did not return a raw dictionary')
        item = dict(captured)
        reserved = {'phase', 'globalIndex', 'globalScheduledMonotonic', 'monotonicSeconds',
                    'elapsedSeconds', 'scheduledSeconds', 'observationCompletedMonotonic',
                    'observationDurationSeconds', 'validatorStartedMonotonic',
                    'validatorCompletedMonotonic', 'writerStartedMonotonic',
                    'streamValidationStatus', 'streamValidationError'}
        if reserved.intersection(item):
            self.fail('PRESTAMPED_SAMPLE', 'raw sampler supplied controller-owned clock or validation fields')
        observation = item.get('processObservation')
        inner_id = observation.get('sampleId') if type(observation) is dict else None
        sample_id = item.get('sampleId', inner_id)
        item.update(phase=name, globalIndex=global_index, sampleId=sample_id,
                    globalScheduledMonotonic=target, monotonicSeconds=start,
                    elapsedSeconds=start - self.phase['phaseClock']['startMonotonic'],
                    scheduledSeconds=local_index * INTERVAL_SECONDS,
                    observationCompletedMonotonic=completed,
                    observationDurationSeconds=completed - start)
        validation_started = self.now()
        error = None
        try:
            if not isinstance(sample_id, str) or not sample_id or sample_id in self.sample_ids:
                raise ValueError('missing or repeated raw sample identity')
            if inner_id is not None and sample_id != inner_id:
                raise ValueError('outer and observer sample identities differ')
            if type(observation) is not dict or observation.get('ownedRoots') != [] or observation.get('ownedProcesses') != []:
                raise ValueError('fixed unloaded phase must have empty owned roots and processes')
            for field in ('availableBytes', 'swapUsedBytes'):
                if type(item.get(field)) is not int or item[field] < 0:
                    raise ValueError('missing or invalid ' + field)
            if completed > deadline:
                raise ValueError('raw observation completed after the fixed phase deadline')
            decision = self.validator(item)
            if decision is False or (isinstance(decision, dict) and decision.get('status', 'PASS') != 'PASS'):
                raise ValueError('raw validator returned an adverse decision')
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        validation_completed = self.now()
        item.update(validatorStartedMonotonic=validation_started,
                    validatorCompletedMonotonic=validation_completed,
                    streamValidationStatus='REFUSED' if error else 'PASS')
        if error:
            item['streamValidationError'] = error
        writer_started = self.now()
        item['writerStartedMonotonic'] = writer_started
        self.writers[name](item)
        writer_completed = self.now()
        self.phase['samples'] += 1
        self.result['samples'] += 1
        self.phase['coverage']['samples'] += 1
        elapsed = item['elapsedSeconds']
        if self.phase_previous is not None:
            gap = start - self.phase_previous
            self.phase['coverage']['maximumGapSeconds'] = max(self.phase['coverage']['maximumGapSeconds'], gap)
        self.phase_previous = start
        coverage = self.phase['coverage']
        if coverage['firstElapsedSeconds'] is None:
            coverage['firstElapsedSeconds'] = elapsed
        coverage['lastElapsedSeconds'] = elapsed
        self.previous = dict(sampleId=sample_id, globalIndex=global_index,
                             monotonicSeconds=start, observationCompletedMonotonic=completed)
        self.result['lastSample'] = dict(self.previous)
        self.event('sample-written', writer_completed, phase=name, globalIndex=global_index,
                   sampleId=sample_id, writerStartedMonotonic=writer_started,
                   writerCompletedMonotonic=writer_completed,
                   validatorStartedMonotonic=validation_started,
                   validatorCompletedMonotonic=validation_completed)
        after_event = self.now()
        if self.service_observer is not None:
            self.service_observer(item, after_event)
        if error:
            self.fail('INVALID_SAMPLE', error)
        if validation_completed > deadline or writer_completed > deadline or after_event > deadline:
            self.fail('PROCESSING_DEADLINE_MISSED', 'validation or durable sample/event write exceeded the fixed phase deadline')
        self.sample_ids.add(sample_id)
        self.phase['validatedSamples'] += 1
        self.result['validatedSamples'] += 1
        available, swap = item['availableBytes'], item['swapUsedBytes']
        old = self.phase['minimumAvailableBytes']
        self.phase['minimumAvailableBytes'] = available if old is None else min(old, available)
        low, high = self.phase['minimumSwapUsedBytes'], self.phase['maximumSwapUsedBytes']
        self.phase['minimumSwapUsedBytes'] = swap if low is None else min(low, swap)
        self.phase['maximumSwapUsedBytes'] = swap if high is None else max(high, swap)
        self.phase['swapRangeBytes'] = self.phase['maximumSwapUsedBytes'] - self.phase['minimumSwapUsedBytes']
        if name == 'admission' and (available < 4 * GIB or self.phase['swapRangeBytes'] > 64 * 1024 ** 2):
            self.fail('ADMISSION_RESOURCE_REFUSED', 'admission availability or swap range crossed its unchanged threshold')

    def finish(self, duration, count, deadline):
        end = self.wait_until(deadline)
        phase = self.phase
        start = phase['phaseClock']['startMonotonic']
        phase['phaseClock']['endMonotonic'] = end
        phase['elapsedSeconds'] = end - start
        if not duration <= end - start <= duration + MAX_GAP_SECONDS:
            self.fail('PHASE_END_GAP', 'the actual fixed phase end exceeded its original three-second tolerance')
        coverage = phase['coverage']
        if (phase['samples'] != count or phase['validatedSamples'] != count
                or coverage['firstElapsedSeconds'] is None
                or coverage['firstElapsedSeconds'] > MAX_GAP_SECONDS
                or not duration - MAX_GAP_SECONDS <= coverage['lastElapsedSeconds'] < duration):
            self.fail('INCOMPLETE_PHASE', 'fixed phase population or endpoint coverage is incomplete')
        coverage['coverageComplete'] = True
        return end

    def run(self):
        origin = self.now()
        self.result['schedule'] = dict(originMonotonic=origin, intervalSeconds=INTERVAL_SECONDS,
                                       maximumGapSeconds=MAX_GAP_SECONDS,
                                       settlingSeconds=self.specs[0][1] if len(self.specs) == 2 else 0,
                                       admissionSeconds=120, intervalReset=False)
        name, duration, count = self.specs[0]
        deadline = self.begin(name, duration, count, origin)
        self.event('phase-enter', origin, phase=name, actualStartMonotonic=origin)
        global_index = 0
        for phase_index, (name, duration, count) in enumerate(self.specs):
            for local_index in range(count):
                target = origin + global_index * INTERVAL_SECONDS
                self.observe(name, local_index, global_index, target, deadline)
                global_index += 1
            self.finish(duration, count, deadline)
            # Capture the actual state transition after the bounded final checks.
            # In particular, do not substitute the nominal scheduled deadline.
            end = self.now()
            self.phase['phaseClock']['endMonotonic'] = end
            self.phase['elapsedSeconds'] = end - self.phase['phaseClock']['startMonotonic']
            if self.phase['elapsedSeconds'] > duration + MAX_GAP_SECONDS:
                self.fail('PHASE_END_GAP', 'final phase checks exceeded the original tolerance')
            self.phase['status'] = 'ADMITTED' if name == 'admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION'
            if phase_index + 1 < len(self.specs):
                next_name, next_duration, next_count = self.specs[phase_index + 1]
                entry = self.now()
                deadline = self.begin(next_name, next_duration, next_count, entry)
                self.event('phase-boundary', entry, fromPhase=name, toPhase=next_name,
                           actualExitMonotonic=end, actualEntryMonotonic=entry)
                if entry - end > MAX_GAP_SECONDS:
                    self.fail('PHASE_TRANSITION_GAP', 'actual phase exit to next entry exceeded three seconds')
            else:
                self.event('phase-exit', end, phase=name, actualEndMonotonic=end)
                recorded = self.now()
                if recorded - end > MAX_GAP_SECONDS:
                    self.fail('PHASE_EXIT_WRITE_GAP', 'recording the final handoff exceeded three seconds')
                if recorded - self.previous['monotonicSeconds'] > MAX_GAP_SECONDS:
                    self.fail('RUNTIME_HANDOFF_GAP', 'final event write already exhausted the next raw sample coverage budget')
                self.result['runtimeHandoffAnchor'] = dict(
                    lastSampleMonotonic=self.previous['monotonicSeconds'],
                    lastSampleId=self.previous['sampleId'], lastGlobalIndex=self.previous['globalIndex'],
                    phaseEndMonotonic=end, handoffRecordedMonotonic=recorded)
        self.result['status'] = 'PREFLIGHT_COMPLETE_ADMITTED'
        return self.result


def run_preflight(sampler, validator, writers, *, event_writer,
                  settling_seconds=600, clock=time.monotonic, sleeper=time.sleep, service_observer=None):
    """Collect fixed 300+60 (or only 60) raw samples under one absolute schedule.

    ``sampler()`` returns raw memory/process evidence; ``validator(item)`` must
    independently validate it or raise. ``writers`` maps phase names to prepared
    durable callbacks. ``event_writer`` records events, including write completion
    after the raw callback returns. No callback may restart or extend a window.
    Failures raise :class:`PreflightRefused` with partial ``.result``; callers must
    retain original raw logs, partial writes and the terminal refusal.
    """
    controller = _Controller(sampler, validator, writers, event_writer,
                             settling_seconds, clock, sleeper, service_observer)
    try:
        return controller.run()
    except PreflightRefused:
        raise
    except Exception as exc:
        controller.fail('PREFLIGHT_CALLBACK_FAILED', type(exc).__name__ + ': ' + str(exc))
