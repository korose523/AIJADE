"""Prospective, process-free scheduling model; deliberately no live adapter.

This can refuse an unsupported serialized observation envelope before entering
an execution stage. Synthetic timing controls are not a workload qualification,
an implementation freeze, raw process evidence, or permission to retry P4.
"""
from dataclasses import dataclass
import math

PERIOD = 2.0
MAX_LOCK_WAIT = 1.25
MAX_OBSERVATION = 2.5
MAX_ACTUAL_GAP = 3.0
SCHEMA = 'aijade.ch7.prospective-lock-scheduler-dummy.v1'


def need(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class CaptureStream:
    name: str
    critical_seconds: float
    post_seconds: float
    offset_seconds: float = 0.0

    def validate(self):
        need(type(self.name) is str and self.name, 'stream identity required')
        need(finite(self.critical_seconds) and self.critical_seconds > 0
             and finite(self.post_seconds) and finite(self.offset_seconds)
             and self.offset_seconds < PERIOD, 'invalid fixed capture service profile')
        need(self.critical_seconds + self.post_seconds <= MAX_OBSERVATION,
             'individual observation service already exceeds the original budget')


@dataclass(frozen=True)
class FiniteWork:
    name: str
    requested_seconds: float
    reserved_seconds: float
    service_seconds: float

    def validate(self):
        need(type(self.name) is str and self.name, 'finite work identity required')
        need(finite(self.requested_seconds) and finite(self.reserved_seconds)
             and self.reserved_seconds > 0 and finite(self.service_seconds), 'invalid finite work profile')
        need(self.service_seconds <= self.reserved_seconds, 'finite work exceeded its declared reservation')


def capture_capacity(streams):
    """Necessary nominal-period bound for the supplied repeated service trace.

    A single measured duration is not WCET, nor a universal hardware lower
    bound. Here it defines one explicit repeated dummy profile. A utilization
    greater than one disproves schedulability of that declared profile before
    any finite launches; smaller utilization is not a sufficient live proof.
    """
    need(type(streams) is list and streams, 'stream population required')
    for stream in streams:
        need(type(stream) is CaptureStream, 'typed capture stream required')
        stream.validate()
    need(len({stream.name for stream in streams}) == len(streams), 'duplicate stream identity')
    demand = sum(stream.critical_seconds for stream in streams)
    utilization = demand / PERIOD
    return dict(schema=SCHEMA, status=('NOMINAL_CAPTURE_PROFILE_UNSCHEDULABLE'
        if utilization > 1 else 'NECESSARY_CAPTURE_CAPACITY_BOUND_ONLY'),
        streams=len(streams), nominalPeriodSeconds=PERIOD,
        serializedCaptureSecondsPerPeriod=demand, utilization=utilization,
        liveFeasibilityProven=False, scientificQualification=False)


def original_fixed_grid_trace(streams, ticks):
    """Show original actual entry, queue, capture and completion separately.

    The capture lock is modeled as one nonpreemptive serial server. An outer
    observation starts at the real requested fixed-grid entry, so contention
    remains inside its complete observation budget. The first violation is
    retained; clocks are never shifted to a later grant to manufacture PASS.
    """
    capture_capacity(streams)
    need(type(ticks) is int and ticks > 0, 'positive fixed tick count required')
    requests = sorted((stream.offset_seconds + PERIOD * index, stream.name, index, stream)
                      for stream in streams for index in range(ticks))
    available = 0.0
    records = []
    for requested, name, index, stream in requests:
        acquired = max(requested, available)
        wait = acquired - requested
        if wait > MAX_LOCK_WAIT:
            records.append(dict(stream=name, index=index, scheduledSeconds=requested,
                actualStartedSeconds=requested, attemptedAcquisitionSeconds=requested,
                deadlineSeconds=requested + MAX_LOCK_WAIT,
                actualStoppedSeconds=requested + MAX_LOCK_WAIT,
                status='CAPTURE_LOCK_TIMEOUT', waitSeconds=MAX_LOCK_WAIT,
                granted=False))
            break
        released = acquired + stream.critical_seconds
        completed = released + stream.post_seconds
        available = released
        valid = completed - requested <= MAX_OBSERVATION
        records.append(dict(stream=name, index=index, scheduledSeconds=requested,
            actualStartedSeconds=requested, acquiredSeconds=acquired,
            releasedSeconds=released, actualCompletedSeconds=completed,
            waitSeconds=wait, wholeObservationSeconds=completed-requested,
            status='DUMMY_TIMING_WITHIN_BOUNDS' if valid else 'WHOLE_OBSERVATION_BUDGET_EXCEEDED',
            granted=True))
        if not valid:
            break
    return dict(schema=SCHEMA, records=records, rawProcessEvidence=False,
        scientificQualification=False, clocksRetimed=False)


def validate_observation(record, previous_start=None):
    """Reject every actual time violation; diagnostic metadata is not a verdict."""
    keys=('scheduledSeconds','actualStartedSeconds','acquiredSeconds','releasedSeconds',
          'actualCompletedSeconds','writerCompletedSeconds')
    need(type(record) is dict and all(finite(record.get(key)) for key in keys), 'actual timing evidence required')
    start, acquired, released, completed, written = (record[key] for key in keys[1:])
    need(record['scheduledSeconds'] <= start <= acquired <= released <= completed <= written,
         'time reversal or planned-time substitution')
    need(acquired-start <= MAX_LOCK_WAIT, 'original capture coordination wait exceeded')
    need(written-start <= MAX_OBSERVATION, 'original complete observation budget exceeded')
    if previous_start is not None:
        need(finite(previous_start) and 0 < start-previous_start <= MAX_ACTUAL_GAP,
             'original actual-start continuity exceeded')
    return True


def simulate_guarded_stage(streams, work, *, ticks, previous_start=None):
    """Minimal fail-closed cooperative slot prototype for feasible dummy traces.

    A finite task is admitted only when its entire declared reservation fits
    before the next original absolute sample slot. Pending work clocks remain
    visible and intent-to-dispatch is conservatively bounded by 1.25 seconds.
    Unsupported real nested profiles refuse here; this is not a complete
    cross-process runtime scheduler and must never be installed as one.
    """
    capacity = capture_capacity(streams)
    if capacity['utilization'] > 1:
        return dict(schema=SCHEMA, status='REFUSED_BEFORE_STAGE_UNSCHEDULABLE_PROFILE',
            capacity=capacity, observations=[], work=[], scientificQualification=False,
            liveAdapterImplemented=False, automaticRetry=False)
    need(len(streams) == 1, 'multi-scope live coordination is not implemented by this dummy candidate')
    need(type(ticks) is int and ticks > 0, 'positive fixed tick count required')
    need(type(work) is list and all(type(job) is FiniteWork for job in work), 'typed finite queue required')
    for job in work:
        job.validate()
    need(len({job.name for job in work}) == len(work), 'duplicate work identity')
    stream = streams[0]
    pending = sorted(work, key=lambda job: (job.requested_seconds, job.name))
    observations, tasks = [], []
    now = 0.0
    previous = previous_start
    for index in range(ticks):
        scheduled = stream.offset_seconds + index*PERIOD
        now = max(now, scheduled)
        started = now
        acquired = now
        released = acquired + stream.critical_seconds
        completed = released + stream.post_seconds
        row=dict(stream=stream.name,index=index,scheduledSeconds=scheduled,
            actualStartedSeconds=started,acquiredSeconds=acquired,releasedSeconds=released,
            actualCompletedSeconds=completed,writerCompletedSeconds=completed)
        validate_observation(row,previous)
        observations.append(row)
        previous=started
        now=completed
        next_slot=stream.offset_seconds+(index+1)*PERIOD
        while pending:
            job=pending[0]
            admitted=max(now,job.requested_seconds)
            if admitted+job.reserved_seconds > next_slot:
                break
            delay=admitted-job.requested_seconds
            need(delay <= MAX_LOCK_WAIT, 'pending finite intent exceeded conservative original wait bound')
            tasks.append(dict(name=job.name,requestedSeconds=job.requested_seconds,
                admittedSeconds=admitted,queueSeconds=delay,lockWaitSeconds=0.0,
                completedSeconds=admitted+job.service_seconds,reservationSeconds=job.reserved_seconds,
                serviceSeconds=job.service_seconds))
            now=admitted+job.service_seconds
            pending.pop(0)
    return dict(schema=SCHEMA,status=('DUMMY_DECLARED_TRACE_WITHIN_BOUNDS_NOT_BACKEND_QUALIFICATION'
        if not pending else 'REFUSED_PENDING_FINITE_WORK_AT_FIXED_END'),
        capacity=capacity,observations=observations,work=tasks,
        pending=[job.name for job in pending],liveAdapterImplemented=False,
        scientificQualification=False,automaticRetry=False,actualReadsPerformed=False)
