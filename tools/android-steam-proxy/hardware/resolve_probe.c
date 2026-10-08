#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include "hardware_symbols.h"

/* Resolution only: never cast an address to a function pointer or invoke it.
 * dlopen executes ELF constructors. Retain the handle and avoid dlclose (and
 * thus unloading). Use _exit after flushing to skip process-exit destructors.
 * The shell checks isolation and SHA256 first. */
int main(int argc, char **argv) {
    if (argc != 2 || argv[1][0] != '/') return 2;
    struct stat original;
    if (stat(argv[1], &original)) return 1;
    void *handle = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!handle) { fprintf(stderr, "FAIL resolve dlopen: %s\n", dlerror()); return 1; }
    unsigned resolved = 0, failures = 0;
    for (unsigned i = 0; i < HARDWARE_FUNCTION_COUNT; ++i) {
        dlerror();
        void *address = dlsym(handle, hardware_symbols[i].name);
        const char *error = dlerror();
        Dl_info owner;
        struct stat st;
        int owned = address && dladdr(address, &owner) && owner.dli_fname &&
            !stat(owner.dli_fname, &st) && st.st_dev == original.st_dev && st.st_ino == original.st_ino;
        if (error || !owned) {
            fprintf(stderr, "FAIL resolve %s: %s\n", hardware_symbols[i].name,
                    error ? error : "null address or outside explicit provider");
            ++failures;
        } else {
            printf("RESOLVED %s %p\n", hardware_symbols[i].name, address);
            ++resolved;
        }
    }
    printf("%s resolve: %u/%u targets; failures=%u; zero Steam API calls\n",
           failures ? "FAIL" : "PASS", resolved, HARDWARE_FUNCTION_COUNT, failures);
    fflush(stdout);
    fflush(stderr);
    _exit(failures ? 1 : 0);
}
