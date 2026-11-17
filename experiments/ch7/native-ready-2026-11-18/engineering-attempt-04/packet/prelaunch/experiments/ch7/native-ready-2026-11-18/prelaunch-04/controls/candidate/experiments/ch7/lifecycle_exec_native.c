/* Original AIJADE identity-ready exec gate. No target executes before byte '1'.
 * Platform clock interfaces are referenced, not copied implementations.
 * Production has no fixture argument, environment switch or alternate target.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <mach/mach_time.h>
#endif

extern char **environ;

static int descriptor(const char *text, int *value) {
    if (!text || !*text) return -1;
    uint64_t result = 0;
    for (const unsigned char *p=(const unsigned char *)text; *p; ++p) {
        if (*p<'0' || *p>'9') return -1;
        result=result*10u+(uint64_t)(*p-'0');
        if (result>(uint64_t)INT_MAX) return -1;
    }
    if (result<=2u) return -1;
    *value=(int)result;
    return 0;
}

static int monotonic_seconds(double *value) {
#if defined(__APPLE__)
    mach_timebase_info_data_t ratio;
    if (mach_timebase_info(&ratio)!=KERN_SUCCESS || !ratio.numer || !ratio.denom) return -1;
    /* Independent integer arithmetic avoids multiplication overflow. CPython
     * 3.12's monotonic clock uses this same system-wide tick/timebase domain. */
    __uint128_t nanos=(__uint128_t)mach_absolute_time()*ratio.numer/ratio.denom;
    if (nanos>(__uint128_t)INT64_MAX) return -1;
    uint64_t ns=(uint64_t)nanos;
    *value=(double)(ns/UINT64_C(1000000000))+(double)(ns%UINT64_C(1000000000))*1e-9;
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC,&now)!=0 || now.tv_sec<0 || now.tv_nsec<0 || now.tv_nsec>=1000000000L) return -1;
    *value=(double)now.tv_sec+(double)now.tv_nsec*1e-9;
#endif
    return isfinite(*value) && *value>=0. ? 0 : -1;
}

static int write_all(int fd, const char *bytes, size_t count) {
    size_t position=0;
    while (position<count) {
        ssize_t written=write(fd,bytes+position,count-position);
        if (written<0 && errno==EINTR) continue;
        if (written<=0) return -1;
        position+=(size_t)written;
    }
    return 0;
}

static int release_byte(int fd) {
    unsigned char byte=0;
    ssize_t count;
    do { count=read(fd,&byte,1); } while (count<0 && errno==EINTR);
    return count==1 && byte=='1' ? 0 : -1;
}

int main(int argc, char **argv) {
    int ready=-1, gate=-1;
    if (argc<5 || strcmp(argv[3],"--") || descriptor(argv[1],&ready) ||
        descriptor(argv[2],&gate) || ready==gate || argv[4][0]!='/') {
        fputs("AIJADE_NATIVE_READY_ARGUMENTS\n",stderr);return 125;
    }
    int ready_flags=fcntl(ready,F_GETFL), gate_flags=fcntl(gate,F_GETFL);
    if (ready_flags<0 || gate_flags<0 || (ready_flags&O_ACCMODE)!=O_WRONLY ||
        (gate_flags&O_ACCMODE)!=O_RDONLY) {
        fputs("AIJADE_NATIVE_READY_DESCRIPTORS\n",stderr);return 125;
    }
    double monotonic;
    if (monotonic_seconds(&monotonic)) {
        fputs("AIJADE_NATIVE_READY_CLOCK\n",stderr);return 125;
    }
    char message[256];
    int length=snprintf(message,sizeof(message),"{\"pid\":%jd,\"parentPid\":%jd,\"readyMonotonic\":%.17g}\n",
        (intmax_t)getpid(),(intmax_t)getppid(),monotonic);
    if (length<=0 || (size_t)length>=sizeof(message) || write_all(ready,message,(size_t)length) || close(ready)) {
        fputs("AIJADE_NATIVE_READY_WRITE\n",stderr);return 125;
    }
    if (release_byte(gate)) {
        fputs("AIJADE_NATIVE_RELEASE_REQUIRED\n",stderr);return 125;
    }
    if (close(gate)) {
        fputs("AIJADE_NATIVE_GATE_CLOSE\n",stderr);return 125;
    }
    execve(argv[4],&argv[4],environ);
    fputs("AIJADE_NATIVE_EXEC_FAILED\n",stderr);
    return 126;
}
