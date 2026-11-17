/* Original AIJADE bulk Darwin process observation. No command/argv is emitted.
 * Uses the installed SDK's kinfo_proc ABI; it is not an atomic global history.
 * Compile-time AIJADE_* function substitutions are for disposable test builds;
 * the production command has no fixture mode, arguments or environment switch.
 */
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#if !defined(__APPLE__)
int main(void) {
    fputs("{\"schema\":\"aijade.mac.bulk-census.v1\",\"status\":\"ERROR\",\"errorCode\":\"UNSUPPORTED_PLATFORM\"}\n", stdout);
    return 1;
}
#else
#include <sys/types.h>
#include <sys/param.h>
#include <sys/proc.h>
#include <sys/sysctl.h>
#include <mach/mach.h>
#include <mach/task_info.h>

#ifndef AIJADE_SYSCTL
#define AIJADE_SYSCTL sysctl
#endif
#ifndef AIJADE_TASK_INFO
#define AIJADE_TASK_INFO task_info
#endif
#ifndef AIJADE_GETPID
#define AIJADE_GETPID getpid
#endif
#ifndef AIJADE_GETPPID
#define AIJADE_GETPPID getppid
#endif
#ifndef AIJADE_CLOCK_GETTIME
#define AIJADE_CLOCK_GETTIME clock_gettime
#endif
#ifndef AIJADE_REALLOC
#define AIJADE_REALLOC realloc
#endif

#define AIJADE_MAX_BYTES ((size_t)16777216)
#define AIJADE_OUTPUT_BYTES ((size_t)4194304)
#define AIJADE_MAX_ATTEMPTS 3

struct attempt {
    size_t capacity;
    size_t returned;
    int result;
    int error;
};

struct capture {
    struct kinfo_proc *items;
    size_t size_query;
    size_t initial_capacity;
    size_t capacity;
    size_t returned;
    size_t count;
    unsigned attempts;
    unsigned growths;
    struct attempt history[AIJADE_MAX_ATTEMPTS];
    uint64_t start_ns;
    uint64_t finish_ns;
    pid_t self_pid;
    pid_t self_parent;
    int64_t self_start_us;
    uint64_t self_rss;
    size_t at_limit;
    const char *error_code;
    int error_number;
};

struct output {
    char *bytes;
    size_t used;
    bool failed;
};

static bool monotonic_ns(uint64_t *value) {
    struct timespec ts;
    if (AIJADE_CLOCK_GETTIME(CLOCK_MONOTONIC, &ts) != 0 || ts.tv_sec < 0 ||
        ts.tv_nsec < 0 || ts.tv_nsec >= 1000000000L ||
        (uint64_t)ts.tv_sec > UINT64_MAX / UINT64_C(1000000000)) return false;
    *value = (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
    return true;
}

static void append(struct output *out, const char *format, ...) {
    if (out->failed) return;
    va_list ap;
    va_start(ap, format);
    int written = vsnprintf(out->bytes + out->used, AIJADE_OUTPUT_BYTES - out->used, format, ap);
    va_end(ap);
    if (written < 0 || (size_t)written >= AIJADE_OUTPUT_BYTES - out->used) {
        out->failed = true;
        return;
    }
    out->used += (size_t)written;
}

static bool fail(struct capture *capture, const char *code, int error_number) {
    capture->error_code = code;
    capture->error_number = error_number;
    return false;
}

/* Capacity is always an integral number of this installed ABI's records. */
static size_t grown_capacity(size_t base) {
    const size_t record = sizeof(struct kinfo_proc);
    const size_t cap = (AIJADE_MAX_BYTES / record) * record;
    if (!record || base > cap) return 0;
    size_t scaled = base + (base / 2) + (base % 2);
    size_t extra = base + 64 * record;
    size_t desired = scaled > extra ? scaled : extra;
    if (desired > cap) return cap;
    if (desired % record) desired += record - (desired % record);
    return desired > cap ? cap : desired;
}

static bool collect(struct capture *capture) {
    int mib[4] = {CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0};
    size_t needed = 0;
    errno = 0;
    if (AIJADE_SYSCTL(mib, 4, NULL, &needed, NULL, 0) != 0)
        return fail(capture, "SIZE_QUERY_FAILED", errno);
    capture->size_query = needed;
    if (!needed) return fail(capture, "EMPTY_SIZE_QUERY", 0);
    if (needed > AIJADE_MAX_BYTES) return fail(capture, "SIZE_QUERY_LIMIT", 0);
    if (needed % sizeof(struct kinfo_proc)) return fail(capture, "MISALIGNED_SIZE_QUERY", 0);
    capture->capacity = grown_capacity(needed);
    capture->initial_capacity = capture->capacity;
    if (!capture->capacity) return fail(capture, "CAPACITY_LIMIT", 0);
    for (unsigned i = 0; i < AIJADE_MAX_ATTEMPTS; ++i) {
        void *allocation = AIJADE_REALLOC(capture->items, capture->capacity);
        if (!allocation) return fail(capture, "ALLOCATION_FAILED", errno);
        capture->items = allocation;
        size_t returned = capture->capacity;
        errno = 0;
        int result = AIJADE_SYSCTL(mib, 4, capture->items, &returned, NULL, 0);
        int error_number = result == 0 ? 0 : errno;
        capture->history[i] = (struct attempt){capture->capacity, returned, result, error_number};
        capture->attempts = i + 1;
        capture->returned = returned;
        if (result == 0) {
            if (returned > capture->capacity) return fail(capture, "RETURNED_LENGTH_EXCEEDS_CAPACITY", 0);
            if (!returned) return fail(capture, "EMPTY_RESPONSE", 0);
            if (returned % sizeof(struct kinfo_proc)) return fail(capture, "MISALIGNED_RESPONSE", 0);
            capture->count = returned / sizeof(struct kinfo_proc);
            return true;
        }
        if (error_number != ENOMEM) return fail(capture, "READ_FAILED", error_number);
        if (i + 1 == AIJADE_MAX_ATTEMPTS) return fail(capture, "READ_ENOMEM_LIMIT", error_number);
        if (returned > AIJADE_MAX_BYTES) return fail(capture, "ENOMEM_REQUIRED_SIZE_LIMIT", error_number);
        size_t base = returned > capture->capacity ? returned : capture->capacity;
        size_t next = grown_capacity(base);
        if (!next || next <= capture->capacity) return fail(capture, "CAPACITY_LIMIT", error_number);
        capture->capacity = next;
        capture->growths += 1;
    }
    return fail(capture, "READ_ATTEMPTS_EXHAUSTED", 0);
}

static int compare_pid(const void *left, const void *right) {
    pid_t a = ((const struct kinfo_proc *)left)->kp_proc.p_pid;
    pid_t b = ((const struct kinfo_proc *)right)->kp_proc.p_pid;
    return (a > b) - (a < b);
}

static const struct kinfo_proc *find_pid(const struct capture *capture, pid_t pid) {
    size_t low = 0, high = capture->count;
    while (low < high) {
        size_t mid = low + (high - low) / 2;
        pid_t value = capture->items[mid].kp_proc.p_pid;
        if (value == pid) return &capture->items[mid];
        if (value < pid) low = mid + 1; else high = mid;
    }
    return NULL;
}

static int64_t start_us(const struct kinfo_proc *item) {
    return (int64_t)item->kp_proc.p_starttime.tv_sec * INT64_C(1000000) +
           (int64_t)item->kp_proc.p_starttime.tv_usec;
}

static const char *category(const struct kinfo_proc *item) {
    char name[sizeof(item->kp_proc.p_comm)];
    size_t length = strnlen(item->kp_proc.p_comm, sizeof(name));
    for (size_t i = 0; i < length; ++i) {
        unsigned char c = (unsigned char)item->kp_proc.p_comm[i];
        name[i] = c >= 'A' && c <= 'Z' ? (char)(c + ('a' - 'A')) : (char)c;
    }
    name[length] = '\0';
    if (strcmp(name, "dotnet") == 0) return "dotnet";
    if (strstr(name, "godot")) return "godot";
    if (strcmp(name, "runner") == 0 || strstr(name, "llama")) return "ollama";
    return "other";
}

static bool validate_records(struct capture *capture) {
    qsort(capture->items, capture->count, sizeof(*capture->items), compare_pid);
    for (size_t i = 0; i < capture->count; ++i) {
        const struct kinfo_proc *item = &capture->items[i];
        pid_t pid = item->kp_proc.p_pid;
        pid_t parent = item->kp_eproc.e_ppid;
        int64_t seconds = (int64_t)item->kp_proc.p_starttime.tv_sec;
        int64_t useconds = (int64_t)item->kp_proc.p_starttime.tv_usec;
        if (pid < 0 || parent < 0 || seconds < 0)
            return fail(capture, "INVALID_PROCESS_IDENTITY", 0);
        /* Prove the microsecond range before subtracting it from INT64_MAX. */
        if (useconds < 0 || useconds >= INT64_C(1000000))
            return fail(capture, "INVALID_PROCESS_IDENTITY", 0);
        if (seconds > (INT64_MAX - useconds) / INT64_C(1000000) ||
            (pid > 0 && seconds == 0 && useconds == 0))
            return fail(capture, "INVALID_PROCESS_IDENTITY", 0);
        if (i && capture->items[i - 1].kp_proc.p_pid == pid) return fail(capture, "DUPLICATE_PID", 0);
        size_t length = strnlen(item->kp_proc.p_comm, sizeof(item->kp_proc.p_comm));
        if (!length) return fail(capture, "EMPTY_COMMAND_FIELD", 0);
        if (length == sizeof(item->kp_proc.p_comm)) return fail(capture, "UNTERMINATED_COMMAND_FIELD", 0);
        bool nonblank = false;
        for (size_t j = 0; j < length; ++j) {
            unsigned char c = (unsigned char)item->kp_proc.p_comm[j];
            if (c < 32 || c == 127) return fail(capture, "CONTROL_COMMAND_FIELD", 0);
            if (c != ' ') nonblank = true;
        }
        if (!nonblank) return fail(capture, "BLANK_COMMAND_FIELD", 0);
        if (length == sizeof(item->kp_proc.p_comm) - 1) capture->at_limit += 1;
        if (pid > 0 && parent == pid) return fail(capture, "IMPOSSIBLE_ANCESTRY", 0);
    }
    /* All identities are validated before any parent's start-time arithmetic. */
    for (size_t i = 0; i < capture->count; ++i) {
        const struct kinfo_proc *item = &capture->items[i];
        pid_t pid = item->kp_proc.p_pid;
        pid_t parent = item->kp_eproc.e_ppid;
        const struct kinfo_proc *parent_item = parent > 0 ? find_pid(capture, parent) : NULL;
        if (parent_item && start_us(parent_item) > start_us(item)) return fail(capture, "PARENT_START_AFTER_CHILD", 0);
        pid_t ancestor = parent;
        size_t depth = 0;
        while (ancestor > 0) {
            if (ancestor == pid || ++depth > capture->count) return fail(capture, "ANCESTRY_CYCLE", 0);
            const struct kinfo_proc *next = find_pid(capture, ancestor);
            if (!next) break; /* A missing required ancestor remains adverse in Python replay. */
            ancestor = next->kp_eproc.e_ppid;
        }
    }
    const struct kinfo_proc *self = find_pid(capture, capture->self_pid);
    if (!self) return fail(capture, "COLLECTOR_ROW_MISSING", 0);
    if (self->kp_eproc.e_ppid != capture->self_parent) return fail(capture, "COLLECTOR_PARENT_CHANGED", 0);
    capture->self_start_us = start_us(self);
    return true;
}

static bool own_rss(struct capture *capture) {
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    kern_return_t result = AIJADE_TASK_INFO(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &count);
    if (result != KERN_SUCCESS || count != MACH_TASK_BASIC_INFO_COUNT)
        return fail(capture, "COLLECTOR_RSS_READ_FAILED", (int)result);
    if (!info.resident_size) return fail(capture, "COLLECTOR_RSS_INVALID", 0);
    if (AIJADE_GETPID() != capture->self_pid || AIJADE_GETPPID() != capture->self_parent)
        return fail(capture, "COLLECTOR_IDENTITY_CHANGED", 0);
    capture->self_rss = (uint64_t)info.resident_size;
    return true;
}

static void emit_error(struct capture *capture) {
    if (!monotonic_ns(&capture->finish_ns)) capture->finish_ns = capture->start_ns;
    printf("{\"schema\":\"aijade.mac.bulk-census.v1\",\"status\":\"ERROR\",\"errorCode\":\"%s\",\"errorNumber\":%d,"
           "\"recordCount\":%zu,\"returnedBytes\":%zu,\"abiRecordBytes\":%zu,\"sizeQueryBytes\":%zu,"
           "\"initialCapacityBytes\":%zu,\"capacityBytes\":%zu,\"readAttempts\":%u,\"enomemGrowths\":%u,"
           "\"maxCapacityBytes\":%zu,\"startedMonotonicNs\":%" PRIu64 ",\"finishedMonotonicNs\":%" PRIu64 ",\"records\":[]}\n",
           capture->error_code ? capture->error_code : "UNSPECIFIED_FAILURE", capture->error_number,
           capture->count, capture->returned, sizeof(struct kinfo_proc), capture->size_query,
           capture->initial_capacity, capture->capacity, capture->attempts, capture->growths,
           AIJADE_MAX_BYTES, capture->start_ns, capture->finish_ns);
}

static bool emit_success(struct capture *capture) {
    struct output out = {malloc(AIJADE_OUTPUT_BYTES), 0, false};
    if (!out.bytes) return fail(capture, "OUTPUT_ALLOCATION_FAILED", errno);
    append(&out, "{\"schema\":\"aijade.mac.bulk-census.v1\",\"status\":\"OK\","
           "\"recordCount\":%zu,\"returnedBytes\":%zu,\"abiRecordBytes\":%zu,\"sizeQueryBytes\":%zu,"
           "\"initialCapacityBytes\":%zu,\"capacityBytes\":%zu,\"readAttempts\":%u,\"enomemGrowths\":%u,"
           "\"maxCapacityBytes\":%zu,\"maxReadAttempts\":%d,\"maxOutputBytes\":%zu,"
           "\"startedMonotonicNs\":%" PRIu64 ",\"finishedMonotonicNs\":",
           capture->count, capture->returned, sizeof(struct kinfo_proc), capture->size_query,
           capture->initial_capacity, capture->capacity, capture->attempts, capture->growths,
           AIJADE_MAX_BYTES, AIJADE_MAX_ATTEMPTS, AIJADE_OUTPUT_BYTES, capture->start_ns);
    size_t finish_position = out.used;
    append(&out, "%20" PRIu64 ",\"clockKind\":\"clock_gettime.CLOCK_MONOTONIC\","
           "\"nameField\":\"kinfo_proc.p_comm\",\"commandNameMaxBytes\":%zu,"
           "\"categoryRule\":\"ascii-casefold-kinfo-comm-v1\",\"atLimitCount\":%zu,"
           "\"recordsSortedByPid\":true,\"notAtomicMachineHistory\":true,"
           "\"collector\":{\"pid\":%d,\"parentPid\":%d,\"createTimeMicros\":%" PRId64 ",\"rssBytes\":",
           UINT64_C(0), sizeof(capture->items[0].kp_proc.p_comm) - 1, capture->at_limit,
           capture->self_pid, capture->self_parent, capture->self_start_us);
    size_t rss_position = out.used;
    append(&out, "%20" PRIu64 "},\"readHistory\":[", UINT64_C(0));
    for (unsigned i = 0; i < capture->attempts; ++i) {
        struct attempt value = capture->history[i];
        append(&out, "%s{\"capacityBytes\":%zu,\"returnedBytes\":%zu,\"result\":%d,\"errno\":%d}",
               i ? "," : "", value.capacity, value.returned, value.result, value.error);
    }
    append(&out, "],\"attemptCapacities\":[");
    for (unsigned i = 0; i < capture->attempts; ++i)
        append(&out, "%s%zu", i ? "," : "", capture->history[i].capacity);
    append(&out, "],\"readErrnos\":[");
    for (unsigned i = 0; i < capture->attempts; ++i)
        append(&out, "%s%d", i ? "," : "", capture->history[i].error);
    append(&out, "],\"records\":[");
    for (size_t i = 0; i < capture->count; ++i) {
        const struct kinfo_proc *item = &capture->items[i];
        size_t length = strnlen(item->kp_proc.p_comm, sizeof(item->kp_proc.p_comm));
        append(&out, "%s{\"pid\":%d,\"parentPid\":%d,\"createTimeMicros\":%" PRId64 ","
               "\"category\":\"%s\",\"commandNameAtLimit\":%s}",
               i ? "," : "", item->kp_proc.p_pid, item->kp_eproc.e_ppid, start_us(item),
               category(item), length == sizeof(item->kp_proc.p_comm) - 1 ? "true" : "false");
    }
    append(&out, "]}\n");
    if (out.failed) { free(out.bytes); return fail(capture, "OUTPUT_LIMIT", 0); }
    if (!own_rss(capture)) { free(out.bytes); return false; }
    if (!monotonic_ns(&capture->finish_ns) || capture->finish_ns < capture->start_ns) {
        free(out.bytes); return fail(capture, "CLOCK_READ_FAILED", errno);
    }
    char replacement[21];
    snprintf(replacement, sizeof(replacement), "%20" PRIu64, capture->finish_ns);
    memcpy(out.bytes + finish_position, replacement, 20);
    snprintf(replacement, sizeof(replacement), "%20" PRIu64, capture->self_rss);
    memcpy(out.bytes + rss_position, replacement, 20);
    bool written = fwrite(out.bytes, 1, out.used, stdout) == out.used && fflush(stdout) == 0;
    free(out.bytes);
    return written || fail(capture, "STDOUT_WRITE_FAILED", errno);
}

int main(int argc, char **argv) {
    (void)argv;
    struct capture capture;
    memset(&capture, 0, sizeof(capture));
    capture.self_pid = AIJADE_GETPID();
    capture.self_parent = AIJADE_GETPPID();
    bool ok = monotonic_ns(&capture.start_ns);
    if (!ok) fail(&capture, "CLOCK_READ_FAILED", errno);
    if (ok && argc != 1) ok = fail(&capture, "ARGUMENTS_NOT_SUPPORTED", 0);
    if (ok) ok = collect(&capture);
    if (ok) ok = validate_records(&capture);
    if (ok) ok = emit_success(&capture);
    if (!ok && capture.error_code && strcmp(capture.error_code, "STDOUT_WRITE_FAILED") == 0)
        fputs("AIJADE_STDOUT_WRITE_FAILED\n", stderr);
    else if (!ok) emit_error(&capture);
    free(capture.items);
    return ok ? 0 : 1;
}
#endif
