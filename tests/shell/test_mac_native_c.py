"""Darwin SDK controls using only a compile-time fake sysctl fixture.

No test invokes the production helper or a real global census. The fixture
includes the unchanged original C source and replaces its collection functions
at compilation. It is not a runtime fixture switch in the production program.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
import uuid

BASE = Path('/Volumes/Untitled/AIJADE')
RUN = BASE / '.research/runs/ch7-mac-census-20261116'
REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'experiments/ch7/mac_bulk_census.c'
LIMIT = 16777216

SHIM = r'''
#include <errno.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/sysctl.h>
#include <mach/mach.h>
#include <mach/task_info.h>

static const char *fixture_mode = "ok";
static unsigned size_calls = 0, read_calls = 0, rss_calls = 0, clock_calls = 0, parent_calls = 0;
static int fixture_sysctl(int *, unsigned int, void *, size_t *, void *, size_t);
static kern_return_t fixture_task_info(task_name_t, task_flavor_t, task_info_t, mach_msg_type_number_t *);
static pid_t fixture_getpid(void);
static pid_t fixture_getppid(void);
static int fixture_clock(clockid_t, struct timespec *);
static void *fixture_realloc(void *, size_t);
static void *fixture_malloc(size_t);
static int fixture_vsnprintf(char *, size_t, const char *, va_list);
static size_t fixture_fwrite(const void *, size_t, size_t, FILE *);

#define AIJADE_SYSCTL fixture_sysctl
#define AIJADE_TASK_INFO fixture_task_info
#define AIJADE_GETPID fixture_getpid
#define AIJADE_GETPPID fixture_getppid
#define AIJADE_CLOCK_GETTIME fixture_clock
#define AIJADE_REALLOC fixture_realloc
#ifdef malloc
#undef malloc
#endif
#ifdef vsnprintf
#undef vsnprintf
#endif
#ifdef fwrite
#undef fwrite
#endif
#define malloc fixture_malloc
#define vsnprintf fixture_vsnprintf
#define fwrite fixture_fwrite
#define main aijade_production_main
#include SOURCE_PLACEHOLDER
#undef main
#undef malloc
#undef vsnprintf
#undef fwrite

static int mode(const char *name) { return strcmp(fixture_mode, name) == 0; }

static void initialize(struct kinfo_proc *row, pid_t pid, pid_t parent, long seconds, const char *name) {
    memset(row, 0, sizeof(*row));
    row->kp_proc.p_pid = pid;
    row->kp_eproc.e_ppid = parent;
    row->kp_proc.p_starttime.tv_sec = seconds;
    row->kp_proc.p_starttime.tv_usec = 0;
    snprintf(row->kp_proc.p_comm, sizeof(row->kp_proc.p_comm), "%s", name);
}

static int fixture_sysctl(int *mib, unsigned int mib_len, void *old, size_t *length, void *new_value, size_t new_length) {
    if (mib_len != 4 || mib[0] != CTL_KERN || mib[1] != KERN_PROC || mib[2] != KERN_PROC_ALL || mib[3] != 0 || new_value || new_length) {
        errno = EINVAL; return -1;
    }
    size_t abi = sizeof(struct kinfo_proc);
    size_t count = mode("self-missing") ? 2 : 3;
    if (!old) {
        size_calls += 1;
        if (mode("size-error")) { errno = EPERM; return -1; }
        if (mode("size-empty")) *length = 0;
        else if (mode("size-large")) *length = 16777217;
        else if (mode("size-misaligned")) *length = count * abi + 1;
        else if (mode("capacity-limit")) *length = (16777216 / abi) * abi;
        else *length = count * abi;
        return 0;
    }
    read_calls += 1;
    if (mode("read-error")) { errno = EACCES; return -1; }
    if (mode("capacity-limit") || mode("enomem-all") ||
        (mode("enomem-success-second") && read_calls < 2) ||
        (mode("enomem-success-third") && read_calls < 3)) {
        errno = ENOMEM; return -1;
    }
    if (mode("enomem-required-limit")) { *length = 16777217; errno = ENOMEM; return -1; }
    if (mode("returned-too-large")) { *length += abi; return 0; }
    if (mode("empty")) { *length = 0; return 0; }
    struct kinfo_proc rows[3];
    initialize(&rows[0], 1, 0, 1, "launchd");
    initialize(&rows[1], 10, 1, 10, "Ollama");
    initialize(&rows[2], 7000, 1, 20, "mac_fixture");
    if (mode("duplicate")) rows[1].kp_proc.p_pid = 1;
    if (mode("negative-pid")) rows[1].kp_proc.p_pid = -1;
    if (mode("negative-parent")) rows[1].kp_eproc.e_ppid = -1;
    if (mode("negative-seconds")) rows[1].kp_proc.p_starttime.tv_sec = -1;
    if (mode("zero-start")) rows[1].kp_proc.p_starttime.tv_sec = 0;
    if (mode("negative-useconds")) rows[1].kp_proc.p_starttime.tv_usec = -1;
    if (mode("million-useconds")) rows[1].kp_proc.p_starttime.tv_usec = 1000000;
    if (mode("parent-future")) rows[0].kp_proc.p_starttime.tv_sec = 15;
    if (mode("self-cycle")) rows[1].kp_eproc.e_ppid = 10;
    if (mode("cycle")) {
        rows[1].kp_eproc.e_ppid = 7000;
        rows[2].kp_eproc.e_ppid = 10;
        rows[2].kp_proc.p_starttime.tv_sec = 10;
    }
    if (mode("blank")) memset(rows[1].kp_proc.p_comm, 0, sizeof(rows[1].kp_proc.p_comm));
    if (mode("space")) snprintf(rows[1].kp_proc.p_comm, sizeof(rows[1].kp_proc.p_comm), "   ");
    if (mode("control")) snprintf(rows[1].kp_proc.p_comm, sizeof(rows[1].kp_proc.p_comm), "a\tb");
    if (mode("unterminated")) memset(rows[1].kp_proc.p_comm, 'x', sizeof(rows[1].kp_proc.p_comm));
    if (mode("at-limit")) memset(rows[1].kp_proc.p_comm, 'x', sizeof(rows[1].kp_proc.p_comm) - 1);
    if (mode("category-dotnet")) snprintf(rows[1].kp_proc.p_comm, sizeof(rows[1].kp_proc.p_comm), "DoTnEt");
    if (mode("category-godot")) snprintf(rows[1].kp_proc.p_comm, sizeof(rows[1].kp_proc.p_comm), "MyGodot");
    if (mode("category-runner")) snprintf(rows[1].kp_proc.p_comm, sizeof(rows[1].kp_proc.p_comm), "RUNNER");
    if (mode("category-llama")) snprintf(rows[1].kp_proc.p_comm, sizeof(rows[1].kp_proc.p_comm), "llama-server");
    if (mode("self-parent")) rows[2].kp_eproc.e_ppid = 2;
    if (mode("max-time") || mode("overflow-micro") || mode("overflow-seconds")) {
        rows[2].kp_proc.p_starttime.tv_sec = INT64_MAX / 1000000;
        rows[2].kp_proc.p_starttime.tv_usec = INT64_MAX % 1000000;
        if (mode("overflow-micro")) rows[2].kp_proc.p_starttime.tv_usec += 1;
        if (mode("overflow-seconds")) { rows[2].kp_proc.p_starttime.tv_sec += 1; rows[2].kp_proc.p_starttime.tv_usec = 0; }
    }
    if (*length < count * abi) { *length = count * abi; errno = ENOMEM; return -1; }
    memcpy(old, rows, count * abi);
    *length = count * abi - (mode("read-misaligned") ? 1 : 0);
    return 0;
}

static kern_return_t fixture_task_info(task_name_t task, task_flavor_t flavor, task_info_t data, mach_msg_type_number_t *count) {
    (void)task;
    rss_calls += 1;
    if (flavor != MACH_TASK_BASIC_INFO) return KERN_INVALID_ARGUMENT;
    if (mode("rss-error")) return KERN_FAILURE;
    mach_task_basic_info_t info = (mach_task_basic_info_t)data;
    memset(info, 0, sizeof(*info));
    info->resident_size = mode("rss-zero") ? 0 : 503808;
    *count = MACH_TASK_BASIC_INFO_COUNT - (mode("rss-count") ? 1 : 0);
    return KERN_SUCCESS;
}

static pid_t fixture_getpid(void) { return 7000; }
static pid_t fixture_getppid(void) {
    parent_calls += 1;
    return mode("identity-changed") && parent_calls > 1 ? 2 : 1;
}
static int fixture_clock(clockid_t clock, struct timespec *value) {
    (void)clock;
    clock_calls += 1;
    if (mode("clock-error")) { errno = EIO; return -1; }
    value->tv_sec = 1;
    value->tv_nsec = (long)clock_calls * 1000;
    if (mode("clock-reversed") && clock_calls == 2) value->tv_sec = 0;
    return 0;
}
static void *fixture_realloc(void *old, size_t length) {
    if (mode("alloc-error")) { errno = ENOMEM; return NULL; }
    return realloc(old, length);
}
static void *fixture_malloc(size_t length) {
    if (mode("output-alloc")) { errno = ENOMEM; return NULL; }
    return malloc(length);
}
static int fixture_vsnprintf(char *target, size_t capacity, const char *format, va_list ap) {
    if (mode("output-limit")) return (int)capacity;
    return vsnprintf(target, capacity, format, ap);
}
static size_t fixture_fwrite(const void *data, size_t size, size_t count, FILE *stream) {
    if (mode("write-error")) { errno = EIO; return 0; }
    return fwrite(data, size, count, stream);
}

int main(int argc, char **argv) {
    fixture_mode = argc > 1 ? argv[1] : "ok";
    char *production_args[] = {(char *)"mac_bulk_census_fixture", (char *)"refused", NULL};
    int code = aijade_production_main(mode("args") ? 2 : 1, production_args);
    fprintf(stderr, "AIJADE_FIXTURE_COUNTS size=%u reads=%u rss=%u\n", size_calls, read_calls, rss_calls);
    return code;
}
'''


@unittest.skipUnless(sys.platform == 'darwin', 'Requires this Mac installed Darwin SDK; no foreign kinfo layout')
class NativeCensusControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = RUN / 'native-controls' / ('attempt-' + uuid.uuid4().hex)
        cls.work.mkdir(parents=True)
        (cls.work / 'tmp').mkdir()
        (cls.work / 'clang-cache').mkdir()
        cls.env = os.environ.copy()
        cls.env.update({'TMPDIR': str(cls.work / 'tmp') + '/',
                        'CLANG_MODULE_CACHE_PATH': str(cls.work / 'clang-cache')})
        cls.source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        clang = subprocess.check_output(['/usr/bin/xcrun', '--find', 'clang'], text=True).strip()
        sdk = subprocess.check_output(['/usr/bin/xcrun', '--show-sdk-path'], text=True).strip()
        cls.fixture = cls.work / 'fixture.c'
        cls.fixture.write_text(SHIM.replace('SOURCE_PLACEHOLDER', json.dumps(str(SOURCE))), encoding='utf-8')
        cls.binary = cls.work / 'mac_bulk_census_fixture'
        command = [clang, '-std=c11', '-O0', '-Wall', '-Wextra', '-Werror', '-isysroot', sdk,
                   str(cls.fixture), '-o', str(cls.binary)]
        result = subprocess.run(command, capture_output=True, env=cls.env, timeout=30)
        (cls.work / 'compile.stdout').write_bytes(result.stdout)
        (cls.work / 'compile.stderr').write_bytes(result.stderr)
        (cls.work / 'fixture-build.json').write_text(json.dumps({
            'scope': 'COMPILE_TIME_FAKE_SYSCTL_ONLY_NOT_GLOBAL_CENSUS_OR_QUALIFICATION',
            'command': command, 'sourceSha256': cls.source_sha, 'exitCode': result.returncode,
            'binarySha256': hashlib.sha256(cls.binary.read_bytes()).hexdigest() if cls.binary.is_file() else None,
        }, ensure_ascii=False, indent=2) + '\n')
        if result.returncode:
            raise RuntimeError('Native fixture compilation failed; artifacts retained at %s\n%s' %
                               (cls.work, result.stderr.decode(errors='replace')))
        if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != cls.source_sha:
            raise RuntimeError('Original C source changed during fixture compilation')

    def invoke(self, mode, expected=None):
        result = subprocess.run([str(self.binary), mode], capture_output=True, env=self.env, timeout=3)
        (self.work / (mode + '.stdout')).write_bytes(result.stdout)
        (self.work / (mode + '.stderr')).write_bytes(result.stderr)
        counts = re.search(rb'AIJADE_FIXTURE_COUNTS size=(\d+) reads=(\d+) rss=(\d+)', result.stderr)
        self.assertIsNotNone(counts, result.stderr)
        observed = tuple(int(x) for x in counts.groups())
        self.assertLessEqual(len(result.stdout), 4194304)
        if mode == 'write-error':
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')
            self.assertIn(b'AIJADE_STDOUT_WRITE_FAILED', result.stderr)
            return result, None, observed
        data = json.loads(result.stdout)
        self.assertEqual(data['schema'], 'aijade.mac.bulk-census.v1')
        if expected is None:
            self.assertEqual(result.returncode, 0, data)
            self.assertEqual(data['status'], 'OK')
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(data['status'], 'ERROR')
            self.assertEqual(data['errorCode'], expected)
        return result, data, observed

    @staticmethod
    def growth(base, abi):
        cap = (LIMIT // abi) * abi
        desired = max((base * 3 + 1) // 2, base + 64 * abi)
        return min(((desired + abi - 1) // abi) * abi, cap)

    def test_one_size_query_and_complete_local_abi_metadata(self):
        result, data, calls = self.invoke('ok')
        self.assertEqual(calls, (1, 1, 1))
        abi = data['abiRecordBytes']
        self.assertGreater(abi, 0)
        self.assertEqual(data['sizeQueryBytes'], 3 * abi)
        self.assertEqual(data['initialCapacityBytes'], self.growth(3 * abi, abi))
        self.assertEqual(data['returnedBytes'], data['recordCount'] * abi)
        self.assertEqual(data['attemptCapacities'], [data['initialCapacityBytes']])
        self.assertEqual(data['readErrnos'], [0])
        self.assertEqual(data['collector'], {'pid': 7000, 'parentPid': 1, 'createTimeMicros': 20000000, 'rssBytes': 503808})
        self.assertTrue(data['notAtomicMachineHistory'])
        self.assertEqual(data['nameField'], 'kinfo_proc.p_comm')
        self.assertEqual(data['categoryRule'], 'ascii-casefold-kinfo-comm-v1')
        self.assertEqual(data['commandNameMaxBytes'], 16)
        self.assertNotIn(b'launchd', result.stdout)
        self.assertNotIn(b'Ollama', result.stdout)

    def test_enomem_growth_is_bounded_and_independently_reconstructible(self):
        for mode, count in [('enomem-success-second', 2), ('enomem-success-third', 3)]:
            with self.subTest(mode=mode):
                _, data, calls = self.invoke(mode)
                self.assertEqual(calls, (1, count, 1))
                self.assertEqual(data['readAttempts'], count)
                self.assertEqual(data['enomemGrowths'], count - 1)
                capacities = [data['initialCapacityBytes']]
                for _ in range(count - 1): capacities.append(self.growth(capacities[-1], data['abiRecordBytes']))
                self.assertEqual(data['attemptCapacities'], capacities)
                self.assertEqual(data['readErrnos'], [errno.ENOMEM] * (count - 1) + [0])
                self.assertEqual([x['capacityBytes'] for x in data['readHistory']], capacities)

    def test_three_enomem_reads_never_start_a_fourth(self):
        _, data, calls = self.invoke('enomem-all', 'READ_ENOMEM_LIMIT')
        self.assertEqual(calls, (1, 3, 0))
        self.assertEqual(data['readAttempts'], 3)
        self.assertEqual(data['enomemGrowths'], 2)

    def test_non_enomem_error_is_never_retried(self):
        _, data, calls = self.invoke('read-error', 'READ_FAILED')
        self.assertEqual(calls, (1, 1, 0))
        self.assertEqual(data['errorNumber'], errno.EACCES)

    def test_size_query_failures_do_not_allocate_a_read(self):
        for mode, code in [('size-error', 'SIZE_QUERY_FAILED'), ('size-empty', 'EMPTY_SIZE_QUERY'),
                           ('size-large', 'SIZE_QUERY_LIMIT'), ('size-misaligned', 'MISALIGNED_SIZE_QUERY')]:
            with self.subTest(mode=mode):
                _, _, calls = self.invoke(mode, code)
                self.assertEqual(calls, (1, 0, 0))

    def test_returned_empty_misaligned_and_over_capacity_frames_are_adverse(self):
        for mode, code in [('empty', 'EMPTY_RESPONSE'), ('read-misaligned', 'MISALIGNED_RESPONSE'),
                           ('returned-too-large', 'RETURNED_LENGTH_EXCEEDS_CAPACITY')]:
            with self.subTest(mode=mode):
                _, _, calls = self.invoke(mode, code)
                self.assertEqual(calls, (1, 1, 0))

    def test_duplicate_or_invalid_identities_are_never_omitted(self):
        for mode, code in [('duplicate', 'DUPLICATE_PID'), ('negative-pid', 'INVALID_PROCESS_IDENTITY'),
                           ('negative-parent', 'INVALID_PROCESS_IDENTITY'), ('negative-seconds', 'INVALID_PROCESS_IDENTITY'),
                           ('zero-start', 'INVALID_PROCESS_IDENTITY'), ('negative-useconds', 'INVALID_PROCESS_IDENTITY'),
                           ('million-useconds', 'INVALID_PROCESS_IDENTITY')]:
            with self.subTest(mode=mode): self.invoke(mode, code)

    def test_parent_time_and_cycles_are_rejected(self):
        for mode, code in [('parent-future', 'PARENT_START_AFTER_CHILD'), ('self-cycle', 'IMPOSSIBLE_ANCESTRY'),
                           ('cycle', 'ANCESTRY_CYCLE')]:
            with self.subTest(mode=mode): self.invoke(mode, code)

    def test_command_integrity_and_declared_at_limit_semantics(self):
        for mode, code in [('blank', 'EMPTY_COMMAND_FIELD'), ('space', 'BLANK_COMMAND_FIELD'),
                           ('control', 'CONTROL_COMMAND_FIELD'), ('unterminated', 'UNTERMINATED_COMMAND_FIELD')]:
            with self.subTest(mode=mode): self.invoke(mode, code)
        _, data, _ = self.invoke('at-limit')
        self.assertEqual(data['atLimitCount'], 1)
        self.assertTrue(next(x for x in data['records'] if x['pid'] == 10)['commandNameAtLimit'])

    def test_int64_microsecond_limit_is_exact_without_signed_overflow(self):
        _, data, _ = self.invoke('max-time')
        self.assertEqual(data['collector']['createTimeMicros'], 9223372036854775807)
        self.invoke('overflow-micro', 'INVALID_PROCESS_IDENTITY')
        self.invoke('overflow-seconds', 'INVALID_PROCESS_IDENTITY')

    def test_collector_actual_rss_failures_never_become_zero(self):
        for mode, code in [('rss-error', 'COLLECTOR_RSS_READ_FAILED'), ('rss-count', 'COLLECTOR_RSS_READ_FAILED'),
                           ('rss-zero', 'COLLECTOR_RSS_INVALID')]:
            with self.subTest(mode=mode):
                _, data, calls = self.invoke(mode, code)
                self.assertEqual(calls[2], 1)
                self.assertNotIn('collector', data)

    def test_collector_identity_is_required_and_cannot_change(self):
        for mode, code in [('self-missing', 'COLLECTOR_ROW_MISSING'), ('self-parent', 'COLLECTOR_PARENT_CHANGED'),
                           ('identity-changed', 'COLLECTOR_IDENTITY_CHANGED')]:
            with self.subTest(mode=mode): self.invoke(mode, code)

    def test_census_and_output_allocation_failures_are_explicit(self):
        _, _, calls = self.invoke('alloc-error', 'ALLOCATION_FAILED')
        self.assertEqual(calls, (1, 0, 0))
        self.invoke('output-alloc', 'OUTPUT_ALLOCATION_FAILED')

    def test_output_cap_and_write_failure_do_not_emit_a_success(self):
        self.invoke('output-limit', 'OUTPUT_LIMIT')
        self.invoke('write-error')

    def test_production_argument_form_is_closed(self):
        _, _, calls = self.invoke('args', 'ARGUMENTS_NOT_SUPPORTED')
        self.assertEqual(calls, (0, 0, 0))

    def test_ascii_category_rules_are_explicit(self):
        for mode, expected in [('category-dotnet', 'dotnet'), ('category-godot', 'godot'),
                               ('category-runner', 'ollama'), ('category-llama', 'ollama')]:
            with self.subTest(mode=mode):
                _, data, _ = self.invoke(mode)
                self.assertEqual(next(x for x in data['records'] if x['pid'] == 10)['category'], expected)

    def test_clock_failures_are_never_complete_observations(self):
        self.invoke('clock-error', 'CLOCK_READ_FAILED')
        self.invoke('clock-reversed', 'CLOCK_READ_FAILED')

    def test_capacity_and_required_size_limits_prevent_unbounded_growth(self):
        for mode, code in [('capacity-limit', 'CAPACITY_LIMIT'), ('enomem-required-limit', 'ENOMEM_REQUIRED_SIZE_LIMIT')]:
            with self.subTest(mode=mode):
                _, _, calls = self.invoke(mode, code)
                self.assertEqual(calls, (1, 1, 0))


if __name__ == '__main__': unittest.main()
