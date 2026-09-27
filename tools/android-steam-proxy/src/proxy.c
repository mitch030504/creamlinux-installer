#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include "symbols.h"
/* Relocations initialize every slot to a fail-closed target before constructors. */
__attribute__((noreturn,visibility("hidden"))) void proxy_unready(void) {
    static const char msg[]="steam proxy: call before initialization completed\n";
    write(STDERR_FILENO,msg,sizeof(msg)-1);
    _exit(127);
}
static void *original_handle; /* Intentionally retained for the process lifetime. */
static __attribute__((noreturn)) void fail(const char *why,const char *detail) {
    fprintf(stderr,"steam proxy: %s: %s\n",why,detail ? detail : "unknown");
    _exit(127);
}
static int same_file(const char *path,const struct stat *expected) {
    struct stat st;
    return path && stat(path,&st)==0 && st.st_dev==expected->st_dev && st.st_ino==expected->st_ino;
}
__attribute__((constructor)) static void initialize(void) {
    const char *path=getenv("CREAMLINUX_ORIGINAL_STEAM_API");
    struct stat original;
    Dl_info self;
    if (!path || path[0]!='/') fail("absolute original path required",path);
    if (stat(path,&original)!=0) fail("cannot stat original",path);
    if (!dladdr((void *)&initialize,&self)) fail("cannot identify proxy",NULL);
    if (same_file(self.dli_fname,&original)) fail("original is proxy itself",path);
    original_handle=dlopen(path,RTLD_NOW|RTLD_LOCAL);
    if (!original_handle) fail("dlopen original",dlerror());
    void *resolved[PROXY_COUNT];
    for (unsigned i=0;i<PROXY_COUNT;i++) {
        dlerror();
        resolved[i]=dlsym(original_handle,proxy_names[i]);
        const char *error=dlerror();
        if (error || !resolved[i]) fail("missing function",proxy_names[i]);
        Dl_info owner;
        if (!dladdr(resolved[i],&owner) || owner.dli_fbase==self.dli_fbase || !same_file(owner.dli_fname,&original))
            fail("target is not in explicit original",proxy_names[i]);
    }
    /* dlopen returns only after this constructor. Reentry while resolving fails. */
    for (unsigned i=0;i<PROXY_COUNT;i++) proxy_targets[i]=resolved[i];
    fprintf(stderr,"steam proxy: resolved %u functions from %s\n",PROXY_COUNT,path);
}
