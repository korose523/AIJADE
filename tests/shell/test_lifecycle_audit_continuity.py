"""Synthetic offline clocks only: no observer, native capture or live window."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'experiments/ch7'))
import lifecycle_audit as a
ORIGINAL_VALIDATE = a._validate_sample


def fixture(settling=True):
    names = ['settling', 'admission'] if settling else ['admission']
    phases = {}; streams = {}; events = []
    origin = 1000.; offset = 0
    for n, name in enumerate(names):
        duration = 600 if name == 'settling' else 120
        start = origin + offset * 2
        if n == 0:
            events.append(dict(event='phase-enter', phase=name, actualStartMonotonic=start, monotonicSeconds=start))
        else:
            events.append(dict(event='phase-boundary', fromPhase='settling', toPhase='admission',
                               actualExitMonotonic=start, actualEntryMonotonic=start, monotonicSeconds=start))
        rows = []
        for local in range(duration // 2):
            index = offset + local; scheduled = origin + index * 2; now = scheduled + .01
            identity = '%032x' % (index + 1)
            row = dict(phase=name, globalIndex=index, sampleId=identity,
                       globalScheduledMonotonic=scheduled, scheduledSeconds=local * 2,
                       elapsedSeconds=now - start, monotonicSeconds=now,
                       observationCompletedMonotonic=now + .01, observationDurationSeconds=.01,
                       validatorStartedMonotonic=now + .02, validatorCompletedMonotonic=now + .025,
                       writerStartedMonotonic=now + .03, availableBytes=6 * 1024**3,
                       swapUsedBytes=1024, rssBytes=0, streamValidationStatus='PASS',
                       processObservation=dict(schemaVersion=3, sampleId=identity, syntheticRawValid=True))
            rows.append(row)
            events.append(dict(event='sample-written', phase=name, globalIndex=index, sampleId=identity,
                               monotonicSeconds=now + .04, writerCompletedMonotonic=now + .04,
                               **{k:row[k] for k in ['writerStartedMonotonic', 'validatorStartedMonotonic', 'validatorCompletedMonotonic']}))
        stamps = [x['monotonicSeconds'] for x in rows]
        phases[name] = dict(status='ADMITTED' if name == 'admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION',
                            samples=len(rows), validatedSamples=len(rows), expectedSamples=len(rows),
                            phaseClock=dict(startMonotonic=start, endMonotonic=start + duration,
                                            requestedSeconds=duration, intervalReset=False), elapsedSeconds=duration,
                            coverage=dict(samples=len(rows), maximumGapSeconds=max(y - x for x, y in zip(stamps, stamps[1:])),
                                          firstElapsedSeconds=stamps[0] - start, lastElapsedSeconds=stamps[-1] - start,
                                          coverageComplete=True), minimumAvailableBytes=6 * 1024**3, swapRangeBytes=0)
        streams[name] = rows; offset += len(rows)
    end = phases['admission']['phaseClock']['endMonotonic']
    events.append(dict(event='phase-exit', phase='admission', actualEndMonotonic=end, monotonicSeconds=end))
    for i, event in enumerate(events):
        event.update(schema=a.EVENT_SCHEMA, eventIndex=i)
    return phases, streams, events


def raw_validator(row, policy, lifecycle_journal=None):
    if row.get('processObservation', {}).get('syntheticRawValid') is not True:
        raise ValueError('synthetic raw evidence adverse')
    return dict(status='PASS', ownedRssBytes=row['rssBytes'], ownedProcesses=[])


class ContinuityAuditControls(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.mock = patch.object(a, '_validate_sample', side_effect=raw_validator)
        self.check = self.mock.start()
        self.addCleanup(self.mock.stop)

    def run_audit(self, **kwargs):
        return a.verify_continuity(*self.data, policy={'synthetic': True}, **kwargs)

    def test_01_complete_600_120_global_raw_population(self):
        result = self.run_audit()
        self.assertEqual(result['samples'], 360)
        self.assertEqual(self.check.call_count, 360)
        self.assertEqual(result['status'], 'CONTINUITY_RAW_AUDIT_PASS')
        self.assertFalse(result['formalHardwareQualification'])

    def test_02_formal_admission_only_has_60_not_360_samples(self):
        self.data = fixture(False)
        self.assertEqual(self.run_audit()['samples'], 60)

    def test_03_each_negative_starts_with_valid_baseline(self):
        self.run_audit()
        self.data[1]['admission'][5]['processObservation']['syntheticRawValid'] = False
        with self.assertRaisesRegex(ValueError, 'raw evidence adverse'):
            self.run_audit()

    def test_04_missing_sample_writer_completion_is_refused(self):
        self.data[2].pop(10)
        for i, e in enumerate(self.data[2]): e['eventIndex'] = i
        with self.assertRaisesRegex(ValueError, 'missing exact writer'):
            self.run_audit()

    def test_05_duplicate_original_sample_id_is_refused(self):
        row = self.data[1]['settling'][1]
        row['sampleId'] = row['processObservation']['sampleId'] = self.data[1]['settling'][0]['sampleId']
        with self.assertRaisesRegex(ValueError, 'duplicated original sample'):
            self.run_audit()

    def test_06_omitted_or_added_slot_is_not_a_smaller_denominator(self):
        self.data[1]['settling'].pop()
        with self.assertRaisesRegex(ValueError, 'population incomplete'):
            self.run_audit()

    def test_07_cross_phase_sample_gap_over3_with_atomic_boundary_refuses(self):
        row = self.data[1]['admission'][0]
        shift = 1.001
        for key in ['monotonicSeconds', 'observationCompletedMonotonic', 'validatorStartedMonotonic',
                    'validatorCompletedMonotonic', 'writerStartedMonotonic']:
            row[key] += shift
        row['elapsedSeconds'] += shift
        event = next(x for x in self.data[2] if x.get('event') == 'sample-written' and x.get('globalIndex') == 300)
        for key in ['monotonicSeconds', 'writerCompletedMonotonic', 'writerStartedMonotonic',
                    'validatorStartedMonotonic', 'validatorCompletedMonotonic']:
            event[key] += shift
        self.data[0]['admission']['coverage']['firstElapsedSeconds'] += shift
        with self.assertRaisesRegex(ValueError, 'cross-phase actual sample start gap'):
            self.run_audit()

    def test_08_original_3point631_boundary_cannot_be_repaired_by_events(self):
        self.data[0]['admission']['phaseClock']['startMonotonic'] += 3.6311725030245725
        self.data[0]['admission']['phaseClock']['endMonotonic'] += 3.6311725030245725
        boundary = next(e for e in self.data[2] if e['event'] == 'phase-boundary')
        boundary['actualEntryMonotonic'] += 3.6311725030245725
        with self.assertRaises(ValueError):
            self.run_audit()

    def test_09_slow_validation_and_write_cannot_cross_fixed_deadline(self):
        row = self.data[1]['admission'][-1]
        row['validatorCompletedMonotonic'] = self.data[0]['admission']['phaseClock']['endMonotonic'] + .01
        with self.assertRaises(ValueError):
            self.run_audit()

    def test_10_summary_swap_zero_cannot_hide_actual_range(self):
        self.data[1]['admission'][10]['swapUsedBytes'] += 65 * 1024**2
        with self.assertRaisesRegex(ValueError, 'swap range'):
            self.run_audit()

    def test_11_summary_population_and_resources_are_rebuilt(self):
        self.data[0]['admission']['minimumAvailableBytes'] += 1
        with self.assertRaisesRegex(ValueError, 'resource summary'):
            self.run_audit()

    def test_12_missing_boundary_cannot_be_filled_from_receipts(self):
        self.data[2][:] = [e for e in self.data[2] if e['event'] != 'phase-boundary']
        for i, e in enumerate(self.data[2]): e['eventIndex'] = i
        with self.assertRaisesRegex(ValueError, 'missing phase boundary'):
            self.run_audit()

    def test_13_reordered_event_clocks_are_refused(self):
        self.data[2][5]['monotonicSeconds'] -= 10
        with self.assertRaisesRegex(ValueError, 'chronology'):
            self.run_audit()

    def test_14_actual_runtime_first_sample_is_required(self):
        with self.assertRaisesRegex(ValueError, 'lacks actual first sample'):
            self.run_audit(runtime_samples=[], runtime_epoch=1720)

    def test_15_runtime_handoff3_exact_accepts_and_3epsilon_refuses(self):
        last = self.data[1]['admission'][-1]['monotonicSeconds']
        row = copy.deepcopy(self.data[1]['admission'][-1])
        row['sampleId'] = row['processObservation']['sampleId'] = 'f' * 32
        row['monotonicSeconds'] = last + 3
        self.run_audit(runtime_samples=[row], runtime_epoch=1720)
        row['monotonicSeconds'] += .000001
        with self.assertRaisesRegex(ValueError, 'actual sample gap'):
            self.run_audit(runtime_samples=[row], runtime_epoch=1720)

    def test_16_runtime_epoch_3epsilon_refuses_without_first_sample_excuse(self):
        row = copy.deepcopy(self.data[1]['admission'][-1])
        row['sampleId'] = row['processObservation']['sampleId'] = 'f' * 32
        row['monotonicSeconds'] = 1723.01
        with self.assertRaisesRegex(ValueError, 'phase boundary gap'):
            self.run_audit(runtime_samples=[row], runtime_epoch=1723.000001)

    def test_17_rss_null_never_becomes_idle_zero(self):
        self.data[1]['settling'][2]['rssBytes'] = None
        with self.assertRaisesRegex(ValueError, 'idle phase contains'):
            self.run_audit()

    def test_18_raw_top_level_and_observer_ids_must_agree(self):
        self.data[1]['admission'][0]['processObservation']['sampleId'] = 'e' * 32
        with self.assertRaisesRegex(ValueError, 'identity projection mismatch'):
            self.run_audit()

    def test_19_actual_new_scheduler_schema_roundtrips_independent_audit(self):
        # Reuse only the deterministic producer fixture; this performs no sleep,
        # subprocess, process observation, or actual scientific window.
        from test_phase_continuity import Fixture
        producer = Fixture()
        def enrich(index, row):
            row['rssBytes'] = 0
            row['processObservation']['syntheticRawValid'] = True
        producer.sample_hook = enrich
        result = producer.run()
        audited = a.verify_continuity(result['phases'], producer.raw, producer.events,
                                      policy={'synthetic': True})
        self.assertEqual(audited['samples'], 360)

    def test_20_settling_resource_description_is_not_admission_threshold(self):
        for row in self.data[1]['settling']:
            row['availableBytes'] = 2 * 1024**3
        self.data[0]['settling']['minimumAvailableBytes'] = 2 * 1024**3
        self.run_audit()

    def test_21_real_positive_phase_handoff_is_not_fabricated_atomic(self):
        shift = .005
        summary = self.data[0]['admission']
        summary['phaseClock']['startMonotonic'] += shift
        summary['phaseClock']['endMonotonic'] += shift
        summary['coverage']['firstElapsedSeconds'] -= shift
        summary['coverage']['lastElapsedSeconds'] -= shift
        for row in self.data[1]['admission']:
            row['elapsedSeconds'] -= shift
        for event in self.data[2]:
            if event['event'] == 'phase-boundary':
                event['actualEntryMonotonic'] += shift
                event['monotonicSeconds'] += shift
            elif event['event'] == 'phase-exit':
                event['actualEndMonotonic'] += shift
                event['monotonicSeconds'] += shift
        self.run_audit()

    def test_22_complete_observer_call_including_postprocessing_has_2point5_budget(self):
        row = dict(monotonicSeconds=1000., observationCompletedMonotonic=1002.5, rssBytes=0,
                   processObservation=dict(schemaVersion=3, startedMonotonic=1000.01, finishedMonotonic=1000.3))
        fake_guard = SimpleNamespace(validate_observation=lambda *args, **kwargs:dict(status='PASS',ownedRssBytes=0))
        with patch.dict(sys.modules, {'mac_process_guard_v3':fake_guard}):
            ORIGINAL_VALIDATE(row, {}, b'original journal')
            row['observationCompletedMonotonic'] += .000001
            with self.assertRaisesRegex(ValueError, 'postprocessing exceeds2.5'):
                ORIGINAL_VALIDATE(row, {}, b'original journal')


if __name__ == '__main__':
    unittest.main()
