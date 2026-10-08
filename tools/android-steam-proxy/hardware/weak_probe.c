#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "weak_cases.h"

static void *open_library(const char *path, int flags) {
    void *h = dlopen(path, RTLD_NOW | flags);
    if (!h) { fprintf(stderr, "FAIL weak dlopen: %s\n", dlerror()); exit(1); }
    return h;
}
static void *lookup(void *h, const char *name) {
    dlerror();
    void *p = dlsym(h, name);
    const char *error = dlerror();
    if (!p || error) { fprintf(stderr, "FAIL weak dlsym %s: %s\n", name, error ? error : "null"); exit(1); }
    return p;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    const char *mode = argv[1];
    int first = !strcmp(mode, "strong-first"), middle = !strcmp(mode, "strong-middle"),
        late = !strcmp(mode, "strong-late"), baseline = !strcmp(mode, "baseline");
    if (!(first || middle || late || baseline)) return 2;
    if (setenv("CREAMLINUX_ORIGINAL_STEAM_API", argv[3], 1)) return 2;
    void *strong = NULL;
    if (first) strong = open_library(argv[4], RTLD_GLOBAL);
    void *proxy = open_library(argv[2], RTLD_LOCAL);
    void *original = open_library(argv[3], RTLD_LOCAL);
    if (middle) strong = open_library(argv[4], RTLD_GLOBAL);
    void *consumer = open_library(argv[5], RTLD_LOCAL);
    if (late) strong = open_library(argv[4], RTLD_GLOBAL);
    uint64_t (*call)(unsigned, uint64_t) = (uint64_t (*)(unsigned, uint64_t))lookup(consumer, "hardware_weak_call");
    void *(*bound)(unsigned) = (void *(*)(unsigned))lookup(consumer, "hardware_weak_address");
    unsigned checks = 0;
    const uint64_t arg = UINT64_C(0x1234567800000000);
    for (unsigned i = 0; i < HARDWARE_WEAK_COUNT; ++i) {
        void *p = lookup(proxy, weak_cases[i].name), *o = lookup(original, weak_cases[i].name);
        void *expected = first || middle ? lookup(strong, weak_cases[i].name) : p;
        uint64_t result = first || middle ? arg + UINT64_C(0x100000) + i : arg + weak_cases[i].pad;
        if (bound(i) != expected || call(i, arg) != result ||
            ((uint64_t (*)(uint64_t))p)(arg) != arg + weak_cases[i].pad ||
            ((uint64_t (*)(uint64_t))o)(arg) != arg + weak_cases[i].pad || p == o) {
            fprintf(stderr, "FAIL weak %s: %s (binding/return/explicit-handle policy)\n", mode, weak_cases[i].name);
            return 1;
        }
        checks += 5;
    }
    printf("PASS weak %s: %u/%u symbols; %u checks; explicit handles retain mock targets\n",
           mode, HARDWARE_WEAK_COUNT, HARDWARE_WEAK_COUNT, checks);
    return 0;
}
