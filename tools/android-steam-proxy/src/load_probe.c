#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include "symbols.h"
/* No Steam API calls and no data writes. dlopen still runs ELF constructors. */
int main(int argc,char **argv) {
    if (argc<2 || argc>3 || argv[1][0]!='/') { fprintf(stderr,"usage: load_probe /absolute/proxy [/absolute/original]\n"); return 2; }
    if (argc==3 && setenv("CREAMLINUX_ORIGINAL_STEAM_API",argv[2],1)) return 2;
    void *h=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if (!h) { fprintf(stderr,"probe dlopen: %s\n",dlerror()); return 1; }
    for (unsigned i=0;i<PROXY_COUNT;i++) {
        if (!dlsym(h,proxy_names[i])) { fprintf(stderr,"probe missing: %s\n",proxy_names[i]); return 1; }
    }
    const char *omitted[]={"g_pSteamClientGameServer","__bss_start","_edata","_end"};
    for (unsigned i=0;i<4;i++) printf("proxy lookup %s: %s\n",omitted[i],dlsym(h,omitted[i])?"FOUND (check owner)":"absent");
    if (argc==3) {
        void *o=dlopen(argv[2],RTLD_NOW|RTLD_LOCAL);
        if (!o) { fprintf(stderr,"probe original: %s\n",dlerror()); return 1; }
        void *data=dlsym(o,"g_pSteamClientGameServer");
        printf("original data address (not read or written): %p\n",data);
    }
    printf("PASS resolved %u proxy functions; zero Steam API calls\n",PROXY_COUNT);
    return 0;
}
