#!/usr/bin/env python3
"""Offline, deterministic controls: no actual sleep, observer or subprocess."""
import copy
import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[2] / 'experiments/ch7/phase_continuity.py'
spec = importlib.util.spec_from_file_location('phase_continuity_controls', MODULE)
continuity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(continuity)


class FakeClock:
    def __init__(self):
        self.value = 1000.0
        self.sleep_calls = []
        self.sleep_hook = None
        self.read_hook = None

    def __call__(self):
        if self.read_hook:
            self.read_hook(self)
        return self.value

    def sleep(self, duration):
        self.sleep_calls.append(duration)
        self.value += duration
        if self.sleep_hook:
            self.sleep_hook(self, duration)


class Fixture:
    def __init__(self):
        self.clock = FakeClock()
        self.raw = {'settling': [], 'admission': []}
        self.events = []
        self.generated = 0
        self.sample_hook = None
        self.validation_hook = None
        self.writer_hook = None
        self.event_hook = None
        self.validations = 0

    def sample(self):
        index = self.generated
        self.generated += 1
        self.clock.value += 0.4
        item = dict(availableBytes=5 * continuity.GIB, swapUsedBytes=20,
                    processObservation=dict(sampleId=f'{index:032x}', ownedRoots=[],
                                            ownedProcesses=[], status='PASS'))
        if self.sample_hook:
            self.sample_hook(index, item)
        return item

    def validate(self, item):
        self.validations += 1
        self.clock.value += 0.02
        if self.validation_hook:
            return self.validation_hook(item)
        if item['processObservation']['status'] != 'PASS':
            raise ValueError('raw observation did not pass')
        return {'status': 'PASS'}

    def write(self, name, item):
        # Real serialization captures the object at this instant, not a pointer
        # later changed by the controller to claim a future writer completion.
        self.raw[name].append(copy.deepcopy(item))
        self.clock.value += 0.01
        if self.writer_hook:
            self.writer_hook(name, item)

    def event(self, item):
        self.events.append(copy.deepcopy(item))
        if self.event_hook:
            self.event_hook(item)

    def run(self, settling=600):
        return continuity.run_preflight(
            self.sample, self.validate,
            {name: lambda item, name=name: self.write(name, item) for name in self.raw},
            event_writer=self.event, settling_seconds=settling,
            clock=self.clock, sleeper=self.clock.sleep)


class PhaseContinuityControls(unittest.TestCase):
    def refused(self, fixture, code, settling=600):
        with self.assertRaises(continuity.PreflightRefused) as caught:
            fixture.run(settling)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.result['status'], 'PREFLIGHT_REFUSED')
        self.assertIsNone(caught.exception.result['runtimeHandoffAnchor'])
        return caught.exception.result

    def test_valid_full_fixed_population_and_absolute_grid(self):
        fixture = Fixture()
        result = fixture.run()
        self.assertEqual(result['status'], 'PREFLIGHT_COMPLETE_ADMITTED')
        self.assertEqual(fixture.validations, 360)
        self.assertEqual(result['samples'], 360)
        self.assertEqual([result['phases'][name]['samples'] for name in fixture.raw], [300, 60])
        all_samples = fixture.raw['settling'] + fixture.raw['admission']
        self.assertEqual([item['globalIndex'] for item in all_samples], list(range(360)))
        self.assertEqual([item['globalScheduledMonotonic'] for item in all_samples],
                         [1000 + index * 2 for index in range(360)])
        self.assertEqual(all_samples[-1]['globalScheduledMonotonic'], 1718)
        self.assertEqual(result['phases']['settling']['phaseClock']['endMonotonic'], 1600)
        self.assertEqual(result['phases']['admission']['phaseClock']['startMonotonic'], 1600)
        self.assertEqual(result['phases']['admission']['phaseClock']['endMonotonic'], 1720)
        self.assertEqual(result['maximumGlobalGapSeconds'], 2)
        self.assertEqual(result['eventCount'], len(fixture.events))
        self.assertEqual([row['eventIndex'] for row in fixture.events], list(range(len(fixture.events))))

    def test_formal_only_120_has_same_schema_and_no_settling(self):
        fixture = Fixture()
        result = fixture.run(0)
        self.assertEqual(set(result['phases']), {'admission'})
        self.assertEqual(result['samples'], 60)
        self.assertEqual(len(fixture.raw['settling']), 0)
        self.assertEqual(result['phases']['admission']['elapsedSeconds'], 120)
        self.assertFalse(any(row['event'] == 'phase-boundary' for row in fixture.events))

    def test_actual_times_and_writer_completion_are_separate(self):
        fixture = Fixture()
        result = fixture.run(0)
        raw = fixture.raw['admission'][0]
        event = next(row for row in fixture.events if row['event'] == 'sample-written')
        self.assertNotIn('writerCompletedMonotonic', raw)
        self.assertEqual(raw['monotonicSeconds'], 1000)
        self.assertLess(raw['monotonicSeconds'], raw['observationCompletedMonotonic'])
        self.assertLessEqual(raw['observationCompletedMonotonic'], raw['validatorStartedMonotonic'])
        self.assertLess(raw['validatorStartedMonotonic'], raw['validatorCompletedMonotonic'])
        self.assertLessEqual(raw['validatorCompletedMonotonic'], raw['writerStartedMonotonic'])
        self.assertLess(raw['writerStartedMonotonic'], event['writerCompletedMonotonic'])
        self.assertEqual(event['writerCompletedMonotonic'], event['monotonicSeconds'])
        self.assertEqual(event['sampleId'], raw['processObservation']['sampleId'])
        self.assertEqual(event['globalIndex'], raw['globalIndex'])
        self.assertAlmostEqual(raw['observationDurationSeconds'], 0.4)
        self.assertEqual(result['runtimeHandoffAnchor']['lastSampleMonotonic'], 1118)

    def test_streaming_cost_does_not_accumulate_at_handoff(self):
        fixture = Fixture()
        fixture.validation_hook = lambda item: setattr(fixture.clock, 'value', fixture.clock.value + 0.7)
        fixture.writer_hook = lambda name, item: setattr(fixture.clock, 'value', fixture.clock.value + 0.2)
        result = fixture.run()
        before = fixture.raw['settling'][-1]
        after = fixture.raw['admission'][0]
        self.assertEqual(after['monotonicSeconds'] - before['monotonicSeconds'], 2)
        self.assertEqual(result['phases']['admission']['phaseClock']['startMonotonic'], 1600)
        self.assertEqual(fixture.validations, 360)

    def test_real_boundary_lateness_never_becomes_planned_clock(self):
        fixture = Fixture()
        def delay_boundary(clock, duration):
            if clock.value == 1600:
                clock.value += 0.05
        fixture.clock.sleep_hook = delay_boundary
        result = fixture.run()
        settling = result['phases']['settling']['phaseClock']
        admission = result['phases']['admission']['phaseClock']
        self.assertAlmostEqual(settling['endMonotonic'], 1600.05)
        self.assertEqual(admission['startMonotonic'], settling['endMonotonic'])
        self.assertAlmostEqual(admission['endMonotonic'] - admission['startMonotonic'], 120)
        self.assertEqual(fixture.raw['admission'][0]['globalScheduledMonotonic'], 1600)
        self.assertAlmostEqual(fixture.raw['admission'][0]['monotonicSeconds'], 1600.05)
        self.assertEqual(len(fixture.raw['admission']), 60)

    def test_exit_and_entry_are_separately_measured(self):
        fixture = Fixture()
        boundary_reads = []
        def transition_cost(clock):
            if clock.value == 1600:
                boundary_reads.append(clock.value)
                if len(boundary_reads) == 3:
                    clock.value += 0.1
        fixture.clock.read_hook = transition_cost
        result = fixture.run()
        event = next(row for row in fixture.events if row['event'] == 'phase-boundary')
        self.assertEqual(event['actualExitMonotonic'], 1600)
        self.assertAlmostEqual(event['actualEntryMonotonic'], 1600.1)
        self.assertEqual(event['monotonicSeconds'], event['actualEntryMonotonic'])
        self.assertEqual(result['phases']['settling']['phaseClock']['endMonotonic'], event['actualExitMonotonic'])
        self.assertEqual(result['phases']['admission']['phaseClock']['startMonotonic'], event['actualEntryMonotonic'])
        self.assertAlmostEqual(result['phases']['admission']['elapsedSeconds'], 120)
        self.assertEqual(fixture.raw['admission'][0]['globalScheduledMonotonic'], 1600)
        self.assertAlmostEqual(fixture.raw['admission'][0]['monotonicSeconds'], 1600.1)

    def test_over_three_second_real_exit_entry_gap_is_adverse(self):
        fixture = Fixture()
        boundary_reads = []
        def transition_cost(clock):
            if clock.value == 1600:
                boundary_reads.append(clock.value)
                if len(boundary_reads) == 3:
                    clock.value += 3.01
        fixture.clock.read_hook = transition_cost
        self.refused(fixture, 'PHASE_TRANSITION_GAP')
        event = next(row for row in fixture.events if row['event'] == 'phase-boundary')
        self.assertGreater(event['actualEntryMonotonic'] - event['actualExitMonotonic'], 3)
        self.assertEqual(fixture.generated, 300)

    def test_late_validator_gap_refused_without_retry(self):
        fixture = Fixture()
        fixture.validation_hook = lambda item: setattr(fixture.clock, 'value', fixture.clock.value + 3)
        result = self.refused(fixture, 'SAMPLE_GAP')
        self.assertEqual(fixture.generated, 1)
        self.assertEqual(result['samples'], 1)

    def test_late_writer_gap_refused_without_retry(self):
        fixture = Fixture()
        fixture.writer_hook = lambda name, item: setattr(fixture.clock, 'value', fixture.clock.value + 3)
        self.refused(fixture, 'SAMPLE_GAP')
        self.assertEqual(fixture.generated, 1)

    def test_omitted_boundary_coverage_refused_even_with_equal_phase_clocks(self):
        fixture = Fixture()
        def omit_boundary(event):
            if event['event'] == 'phase-boundary':
                fixture.clock.value += 1.1
        fixture.event_hook = omit_boundary
        result = self.refused(fixture, 'SAMPLE_GAP')
        self.assertEqual(result['phases']['settling']['samples'], 300)
        self.assertEqual(result['phases']['admission']['samples'], 0)
        self.assertEqual(result['phases']['admission']['phaseClock']['startMonotonic'],
                         result['phases']['settling']['phaseClock']['endMonotonic'])

    def test_exact_three_second_cross_boundary_gap_accepted(self):
        fixture = Fixture()
        fixture.event_hook = lambda event: setattr(fixture.clock, 'value', fixture.clock.value + 1) if event['event'] == 'phase-boundary' else None
        result = fixture.run()
        self.assertEqual(result['maximumGlobalGapSeconds'], 3)

    def test_three_seconds_plus_epsilon_cross_boundary_refused(self):
        fixture = Fixture()
        fixture.event_hook = lambda event: setattr(fixture.clock, 'value', fixture.clock.value + 1.00001) if event['event'] == 'phase-boundary' else None
        self.refused(fixture, 'SAMPLE_GAP')

    def test_raw_observation_cannot_finish_after_fixed_deadline(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: setattr(fixture.clock, 'value', fixture.clock.value + 2) if index == 299 else None
        result = self.refused(fixture, 'INVALID_SAMPLE')
        raw = fixture.raw['settling'][-1]
        self.assertGreater(raw['observationCompletedMonotonic'], 1600)
        self.assertEqual(raw['streamValidationStatus'], 'REFUSED')
        self.assertEqual(result['samples'], 300)
        self.assertNotIn('admission', result['phases'])

    def test_validator_cannot_finish_after_fixed_deadline(self):
        fixture = Fixture()
        fixture.validation_hook = lambda item: setattr(fixture.clock, 'value', fixture.clock.value + 2) if item['globalIndex'] == 299 else None
        self.refused(fixture, 'PROCESSING_DEADLINE_MISSED')

    def test_writer_cannot_finish_after_fixed_deadline(self):
        fixture = Fixture()
        fixture.writer_hook = lambda name, item: setattr(fixture.clock, 'value', fixture.clock.value + 2) if item['globalIndex'] == 299 else None
        self.refused(fixture, 'PROCESSING_DEADLINE_MISSED')

    def test_fixed_end_oversleep_cannot_extend_phase(self):
        fixture = Fixture()
        fixture.clock.sleep_hook = lambda clock, duration: setattr(clock, 'value', clock.value + 3.1) if clock.value == 1600 else None
        self.refused(fixture, 'PHASE_END_GAP')

    def test_invalid_raw_observation_is_preserved_and_stops(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item['processObservation'].update(status='UNKNOWN')
        self.refused(fixture, 'INVALID_SAMPLE')
        self.assertEqual(fixture.generated, 1)
        self.assertEqual(fixture.raw['settling'][0]['processObservation']['status'], 'UNKNOWN')
        self.assertEqual(fixture.raw['settling'][0]['streamValidationStatus'], 'REFUSED')

    def test_adverse_validator_return_is_not_pass(self):
        fixture = Fixture()
        fixture.validation_hook = lambda item: {'status': 'UNKNOWN'}
        self.refused(fixture, 'INVALID_SAMPLE')

    def test_unloaded_phase_cannot_adopt_owned_processes(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item['processObservation'].update(ownedRoots=[{'pid': 1}])
        self.refused(fixture, 'INVALID_SAMPLE')

    def test_duplicate_identity_refused(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item['processObservation'].update(sampleId='same')
        self.refused(fixture, 'INVALID_SAMPLE')
        self.assertEqual(fixture.generated, 2)

    def test_actual_clock_reversal_refused(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: setattr(fixture.clock, 'value', fixture.clock.value - 2)
        self.refused(fixture, 'CLOCK_REVERSED_OR_INVALID')

    def test_nonfinite_clock_refused(self):
        fixture = Fixture()
        fixture.clock.value = float('nan')
        self.refused(fixture, 'CLOCK_REVERSED_OR_INVALID')

    def test_admission_memory_and_swap_limits_are_unchanged(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item.update(availableBytes=4 * continuity.GIB, swapUsedBytes=(index % 2) * 64 * 1024 ** 2)
        result = fixture.run(0)
        self.assertEqual(result['phases']['admission']['minimumAvailableBytes'], 4 * continuity.GIB)
        self.assertEqual(result['phases']['admission']['swapRangeBytes'], 64 * 1024 ** 2)
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item.update(availableBytes=4 * continuity.GIB - 1)
        self.refused(fixture, 'ADMISSION_RESOURCE_REFUSED', 0)
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item.update(swapUsedBytes=index * (64 * 1024 ** 2 + 1))
        self.refused(fixture, 'ADMISSION_RESOURCE_REFUSED', 0)

    def test_broken_writer_retains_partial_refusal_without_acceptance(self):
        fixture = Fixture()
        def broken(name, item):
            raise OSError('fixture disk error')
        fixture.writer_hook = broken
        self.refused(fixture, 'PREFLIGHT_CALLBACK_FAILED')
        self.assertEqual(len(fixture.raw['settling']), 1)

    def test_final_event_write_cannot_consume_runtime_coverage_budget(self):
        fixture = Fixture()
        fixture.event_hook = lambda event: setattr(fixture.clock, 'value', fixture.clock.value + 1.1) if event['event'] == 'phase-exit' else None
        self.refused(fixture, 'RUNTIME_HANDOFF_GAP', 0)

    def test_prestamped_raw_clock_is_not_silently_rewritten(self):
        fixture = Fixture()
        fixture.sample_hook = lambda index, item: item.update(monotonicSeconds=1)
        self.refused(fixture, 'PRESTAMPED_SAMPLE')

    def test_no_early_sleep_reset_or_unsupported_duration(self):
        fixture = Fixture()
        fixture.clock.sleep_hook = lambda clock, duration: setattr(clock, 'value', clock.value - 0.1)
        self.refused(fixture, 'EARLY_SLEEP_RETURN')
        with self.assertRaises(ValueError):
            Fixture().run(1)


if __name__ == '__main__':
    unittest.main()
