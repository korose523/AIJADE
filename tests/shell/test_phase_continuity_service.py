"""Actual callback-return clocks, using only a deterministic fake clock."""
import unittest
from test_phase_continuity import Fixture, continuity


class CompleteServiceControls(unittest.TestCase):
    def invoke(self, fixture, observer):
        return continuity.run_preflight(fixture.sample, fixture.validate,
            {name:lambda row,name=name:fixture.write(name,row) for name in fixture.raw},
            event_writer=fixture.event, clock=fixture.clock, sleeper=fixture.clock.sleep,
            service_observer=observer)

    def test_return_clock_includes_event_callback_and_diagnostic_write(self):
        f=Fixture(); observed=[]
        def event(item):
            if item['event']=='sample-written':
                f.clock.value += .35
        f.event_hook=event
        result=self.invoke(f,lambda row,completed:observed.append((row['sampleId'],completed,row['monotonicSeconds'])))
        self.assertEqual(result['validatedSamples'],360)
        self.assertEqual(len(observed),360)
        for sid,completed,started in observed:
            self.assertAlmostEqual(completed-started,.78)
            self.assertEqual(sid,f'{int(sid,16):032x}')

    def test_service_refusal_retains_raw_event_and_partial_phase(self):
        f=Fixture()
        def refused(row,completed):
            raise ValueError('engineering service refused after actual callback return')
        with self.assertRaises(continuity.PreflightRefused) as caught:
            self.invoke(f,refused)
        self.assertEqual(caught.exception.result['reasonCode'],'PREFLIGHT_CALLBACK_FAILED')
        self.assertEqual(len(f.raw['settling']),1)
        self.assertEqual(f.events[-1]['event'],'sample-written')
        self.assertEqual(caught.exception.result['validatedSamples'],0)


if __name__=='__main__':
    unittest.main()
