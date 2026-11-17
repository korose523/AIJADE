"""Independent offline event-version index, never a production PASS cache.

The preserved full cold oracle validates the entire final journal once. This
separate implementation builds historical versions and must match its final
and declared intermediate exact states. Every original sample still receives
full raw-guard cold validation and actual prefix hash/content verification.
"""
from bisect import bisect_right
import copy
import hashlib
import json


def need(value, message):
    if not value:
        raise ValueError(message)


def typed_equal(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return set(a) == set(b) and all(typed_equal(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(typed_equal(x, y) for x, y in zip(a, b))
    return a == b


class EventIndex:
    def __init__(self, raw, oracle, source_commit, policy_sha256):
        need(type(raw) is bytes and 0 < len(raw) <= 16*1024**2 and raw.endswith(b'\n'), 'exact complete bounded journal bytes')
        # This call is the retained independent full cold oracle, not the
        # producer's replay or its incremental cursor.
        full = oracle(raw, source_commit, policy_sha256)
        need(not full['launchRefusals'] and not full['discovered'], 'engineering journal contains refused or undeclared identity events')
        self.raw = raw
        self.events = []
        self.offsets = [0]
        self.leases = {}
        self.scopes = {}
        for line in raw.splitlines(keepends=True):
            event = json.loads(line)
            self.events.append(event)
            self.offsets.append(self.offsets[-1]+len(line))
            seq, kind, data = event['seq'], event['event'], event['data']
            if kind in ('CONTROLLER_REGISTER', 'FINITE_REGISTER'):
                value = dict(copy.deepcopy(data), registerSeq=seq, registerMonotonic=event['monotonicSeconds'],
                             releaseSeq=None, waitSeq=None, exitCode=None, absence=None)
                self._add(self.leases, data['leaseId'], seq, value)
            elif kind == 'RELEASE':
                key = data['leaseId']
                value = copy.deepcopy(self.leases[key][-1][1])
                value.update(releaseSeq=seq, releaseMonotonic=event['monotonicSeconds'])
                self._add(self.leases, key, seq, value)
            elif kind == 'WAIT':
                key = data['leaseId']
                value = copy.deepcopy(self.leases[key][-1][1])
                value.update(waitSeq=seq, exitCode=data['exitCode'], reapedMonotonic=data['reapedMonotonic'])
                value['absence'] = dict(witnessKind='PARENT_WAIT_REAPED', identity=copy.deepcopy(value['identity']),
                    parentIdentity=copy.deepcopy(value['parentIdentity']), eventSeq=seq,
                    reapedMonotonic=data['reapedMonotonic'], exitCode=data['exitCode'])
                value['absenceWitnessKind'] = 'PARENT_WAIT_REAPED'
                self._add(self.leases, key, seq, value)
            elif kind == 'ABSENCE':
                keys = [key for key, versions in self.leases.items()
                        if versions[-1][1]['identity'] == data['identity']]
                need(len(keys) == 1, 'independent index absence lease identity')
                key = keys[0]
                value = copy.deepcopy(self.leases[key][-1][1])
                value['absence'] = dict(copy.deepcopy(data), eventSeq=seq, witnessKind='COMPLETE_NATIVE_ABSENCE')
                value['absenceWitnessKind'] = 'COMPLETE_NATIVE_ABSENCE'
                self._add(self.leases, key, seq, value)
            elif kind == 'SCOPE_OPEN':
                self._add(self.scopes, data['scopeId'], seq, dict(copy.deepcopy(data), openSeq=seq, closeSeq=None))
            elif kind == 'SCOPE_CLOSE':
                key = data['scopeId']
                value = copy.deepcopy(self.scopes[key][-1][1])
                value['closeSeq'] = seq
                self._add(self.scopes, key, seq, value)
            else:
                raise ValueError('undeclared engineering event kind: '+str(kind))
        self.context = full['runId']
        need(typed_equal(self.state(len(self.events)), full), 'independent final event index disagrees with preserved oracle')

    @staticmethod
    def _add(table, key, seq, value):
        versions = table.setdefault(key, [])
        need(not versions or seq > versions[-1][0], 'independent version chronology')
        versions.append((seq, value))

    @staticmethod
    def _project(table, sequence):
        output = {}
        for key, versions in table.items():
            index = bisect_right([v[0] for v in versions], sequence)-1
            if index >= 0:
                output[key] = copy.deepcopy(versions[index][1])
        return output

    def state(self, sequence):
        need(type(sequence) is int and 0 <= sequence <= len(self.events), 'actual original sequence cutoff')
        # The event list is a new prefix list of the already cold-validated
        # immutable original event objects. Audit consumers never mutate it;
        # mutation controls must copy their baseline explicitly.
        return dict(events=self.events[:sequence], leases=self._project(self.leases, sequence),
                    scopes=self._project(self.scopes, sequence), discovered={}, launchRefusals=[],
                    runId=self.context if sequence else None)

    def prefix(self, count, expected_sha256, expected_sequence):
        need(type(count) is int and 0 < count <= len(self.raw), 'actual prefix byte count')
        need(type(expected_sequence) is int and 0 < expected_sequence <= len(self.events)
             and type(expected_sha256) is str and len(expected_sha256) == 64,
             'actual prefix cutoff/hash types')
        sequence = bisect_right(self.offsets, count)-1
        need(self.offsets[sequence] == count and sequence == expected_sequence, 'prefix byte/event boundary differs')
        prefix = self.raw[:count]
        need(hashlib.sha256(prefix).hexdigest() == expected_sha256, 'actual original prefix byte hash differs')
        return prefix, self.state(sequence)
