/*
 * GLIBC compatibility wrappers.
 *
 * Fedora 44 (GLIBC 2.43) introduced new symbol versions for log10f,
 * strtol, and sscanf.  Binaries linked on Fedora 44 require these
 * versions at runtime, making the .so unusable on Debian 13 (GLIBC 2.40)
 * and other distros with older GLIBC.
 *
 * --wrap redirects all internal calls to our implementations that only
 * need GLIBC <= 2.35.
 */
#include <math.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>

/* log10f: GLIBC_2.43 → compute via logf (GLIBC_2.2.5) */
float __wrap_log10f(float x) {
    return logf(x) * 0.43429448190325176f;  /* 1/ln(10) */
}

/* strtol: __isoc23_strtol@GLIBC_2.38 → strtol@GLIBC_2.2.5 */
long __wrap___isoc23_strtol(const char *nptr, char **endptr, int base) {
    return strtol(nptr, endptr, base);
}

int __wrap___isoc23_vsscanf(const char *str, const char *fmt, va_list ap);

/* sscanf: __isoc23_sscanf@GLIBC_2.38 → legacy sscanf */
int __wrap___isoc23_sscanf(const char *str, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int r = __wrap___isoc23_vsscanf(str, fmt, ap);
    va_end(ap);
    return r;
}

/* vsscanf: __isoc23_vsscanf@GLIBC_2.38 → vsscanf@GLIBC_2.2.5 */
int __wrap___isoc23_vsscanf(const char *str, const char *fmt, va_list ap) {
    return vsscanf(str, fmt, ap);
}
