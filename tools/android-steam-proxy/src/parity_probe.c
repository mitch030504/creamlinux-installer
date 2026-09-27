#define _GNU_SOURCE
#include <dlfcn.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Signatures verified against Valve headers; exact-reference pre-init behavior
 * verified by disassembly. See PARITY.md. No extensible function-name option.
 * run_parity.sh pins the full original SHA-256 before invoking this executable.
 */
typedef bool (*IsSteamRunningFn)(void);
typedef int32_t (*GetHSteamUserFn)(void);
typedef int32_t (*GetHSteamPipeFn)(void);
_Static_assert(sizeof(bool) == 1 && sizeof(int32_t) == 4, "unexpected ABI");
static const char *const names[] = {
    "SteamAPI_IsSteamRunning", "SteamAPI_GetHSteamUser", "SteamAPI_GetHSteamPipe"
};

static int error(const char *stage, const char *detail, int status) {
    fprintf(stderr, "parity: %s: %s\n", stage, detail ? detail : "unknown");
    return status;
}

static bool same_file(const struct stat *a, const struct stat *b) {
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino;
}

static bool identify(const char *path, char *canonical, struct stat *st) {
    return realpath(path, canonical) && stat(canonical, st) == 0 && S_ISREG(st->st_mode);
}

static void json_string(const char *text) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32 || *p >= 127) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static void json_file(const char *path, const struct stat *st) {
    printf("{\"path\":");
    json_string(path);
    printf(",\"device\":%ju,\"inode\":%ju,\"size\":%jd,\"mtime\":%jd}",
           (uintmax_t)st->st_dev, (uintmax_t)st->st_ino,
           (intmax_t)st->st_size, (intmax_t)st->st_mtime);
}

int main(int argc, char **argv) {
    bool proxy = argc > 1 && strcmp(argv[1], "proxy") == 0;
    bool direct = argc > 1 && strcmp(argv[1], "direct") == 0;
    if ((!direct && !proxy) || (direct && argc != 3) || (proxy && argc != 4))
        return error("usage", "parity_probe direct /absolute/original.so OR "
                     "parity_probe proxy /absolute/proxy.so /absolute/original.so", 2);
    for (int i = 2; i < argc; i++)
        if (argv[i][0] != '/') return error("path", "absolute library paths required", 2);
    const char *preload = getenv("LD_PRELOAD");
    if (preload && *preload) return error("environment", "LD_PRELOAD must be unset", 2);
    char original[PATH_MAX], library[PATH_MAX];
    struct stat original_st, library_st;
    if (!identify(argv[proxy ? 3 : 2], original, &original_st))
        return error("original", "cannot identify regular original file", 1);
    if (!identify(argv[2], library, &library_st))
        return error("library", "cannot identify regular library file", 1);
    if (proxy && same_file(&original_st, &library_st))
        return error("path", "proxy and original must be different files", 2);
    if ((proxy && setenv("CREAMLINUX_ORIGINAL_STEAM_API", original, 1)) ||
        (direct && unsetenv("CREAMLINUX_ORIGINAL_STEAM_API")))
        return error("environment", "cannot configure explicit original", 1);

    /* Bound loader/call hangs; a timeout is inconclusive, never parity. */
    if (signal(SIGALRM, SIG_DFL) == SIG_ERR) return error("timeout", "signal setup failed", 1);
    alarm(15);
    fprintf(stderr, "parity: %s: loading %s; original %s; no SteamAPI_Init\n",
            argv[1], library, original);
    void *handle = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!handle) return error("dlopen", dlerror(), 1);
    void *resolved[3];
    /* Resolve/validate the entire allowlist before making any API call. */
    for (unsigned i = 0; i < 3; i++) {
        dlerror();
        resolved[i] = dlsym(handle, names[i]);
        const char *detail = dlerror();
        if (detail || !resolved[i]) return error("resolve", detail ? detail : names[i], 1);
        Dl_info owner;
        struct stat owner_st;
        if (!dladdr(resolved[i], &owner) || !owner.dli_fname ||
            stat(owner.dli_fname, &owner_st) || !same_file(&owner_st, &library_st))
            return error("owner", "allowlisted symbol is not in explicit loaded library", 1);
    }
    fprintf(stderr, "parity: calling %s\n", names[0]);
    bool running = ((IsSteamRunningFn)resolved[0])();
    fprintf(stderr, "parity: calling %s\n", names[1]);
    int32_t user = ((GetHSteamUserFn)resolved[1])();
    fprintf(stderr, "parity: calling %s\n", names[2]);
    int32_t pipe = ((GetHSteamPipeFn)resolved[2])();
    printf("PARITY_JSON {\"schema_version\":1,\"status\":\"ok\",\"mode\":");
    json_string(argv[1]);
    printf(",\"steam_api_init_called\":false,\"original\":");
    json_file(original, &original_st);
    printf(",\"loaded_library\":");
    json_file(library, &library_st);
    printf(",\"results\":{\"SteamAPI_IsSteamRunning\":%s,"
           "\"SteamAPI_GetHSteamUser\":%" PRId32 ",\"SteamAPI_GetHSteamPipe\":%" PRId32 "}}\n",
           running ? "true" : "false", user, pipe);
    if (fflush(stdout)) return error("output", "cannot flush result", 1);
    /* Retain DSOs and bypass finalizers: there is no initialized API to shut down. */
    _exit(0);
}
