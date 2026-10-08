#define _GNU_SOURCE
#include "mock.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
#ifdef TARGET_SURFACE_TEST
#include "abi_names.h"
#else
#define abi_lookup_name(name) (name)
#endif
#ifdef STATIC_ABI
void initialize_static_targets(void);
void *static_lookup(const char *);
#define lookup(h,n) static_lookup(abi_lookup_name(n))
#else
static void *lookup(void *h,const char *n) { void *p=dlsym(h,abi_lookup_name(n)); if (!p) { fprintf(stderr,"dlsym %s: %s\n",n,dlerror()); exit(1); } return p; }
#endif
#define LOAD(name) __typeof__(&name) p_##name = (__typeof__(&name))lookup(h,#name)
#ifndef MOCK_PAD_COUNT
#define MOCK_PAD_COUNT 1030
#endif
static uint64_t callback(uint64_t n) { return n*17; }
int main(int argc, char **argv) {
#ifdef STATIC_ABI
    if (argc==2 && !strcmp(argv[1],"--uninitialized")) {
        ((int32_t (*)(int32_t,int32_t))static_lookup(abi_lookup_name("mock_int")))(1,2);
        return 1; /* Must exit 127 in the initial slot target. */
    }
    void *h=NULL; (void)h;
    initialize_static_targets();
#else
    if (argc != 3 || argv[1][0]!='/' || argv[2][0]!='/') { fprintf(stderr,"usage: abi_test /absolute/proxy /absolute/mock_original\n"); return 2; }
    if (setenv("CREAMLINUX_ORIGINAL_STEAM_API",argv[2],1)) return 2;
    void *h=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if (!h) { fprintf(stderr,"dlopen: %s\n",dlerror()); return 1; }
#endif
    LOAD(mock_int); CHECK(p_mock_int(-12345,6789)==-31479);
    LOAD(mock_u64); CHECK(p_mock_u64(0x1234567887654321ULL,0xabcdef0123456789ULL)==(0x1234567887654321ULL ^ 0xabcdef0123456789ULL));
    char buffer[64]; LOAD(mock_ptr); CHECK(p_mock_ptr(buffer,29)==buffer+29);
    LOAD(mock_i8); CHECK(p_mock_i8(1,2,3,4,5,6,7,8)==204);
    LOAD(mock_i12); CHECK(p_mock_i12(1,2,3,4,5,6,7,8,9,10,11,12)==650);
    LOAD(mock_float); CHECK(p_mock_float(1.25f,2.5f)==6.25f);
    LOAD(mock_double); CHECK(p_mock_double(1.5,2.25)==8.25);
    LOAD(mock_f8); CHECK(p_mock_f8(1,2,3,4,5,6,7,8)==204);
    LOAD(mock_f12); CHECK(p_mock_f12(1,2,3,4,5,6,7,8,9,10,11,12)==650);
    LOAD(mock_mixed); CHECK(p_mock_mixed(7,1.5,11,2.25f,buffer,13,3.5)==38.25);
    LOAD(mock_pair); Pair pair=p_mock_pair(0x123456789abcdef0ULL,0xfedcba9876543210ULL); CHECK(pair.a==0x123456789abcdef0ULL && pair.b==0xfedcba9876543210ULL);
    LOAD(mock_big); Big big=p_mock_big(17,29); CHECK(big.a==17 && big.b==29 && big.c==46 && big.d==12);
    LOAD(mock_hfa); Hfa hf=p_mock_hfa((Hfa){1,2,3,4},0.5); CHECK(hf.a==1.5 && hf.b==2.5 && hf.c==3.5 && hf.d==4.5);
    LOAD(mock_vector); Vec v=p_mock_vector((Vec){7,11},(Vec){13,17}); CHECK(v[0]==20 && v[1]==28);
    LOAD(mock_variadic); CHECK(p_mock_variadic(5,1.0,2.0,3.0,4.0,5.0)==55);
    LOAD(mock_callback); CHECK(p_mock_callback(callback,19)==324);
    LOAD(mock_indirect_arg); CHECK(p_mock_indirect_arg((Big){1,2,3,4},7)==37);
    /* Repeat and reach table slots across 4 KiB page boundaries. */
    for (unsigned i=0;i<MOCK_PAD_COUNT;i++) {
        char name[40]; snprintf(name,sizeof(name),"mock_pad_%04u",i);
        uint64_t (*f)(uint64_t)=(uint64_t (*)(uint64_t))lookup(h,name);
        CHECK(f(0x1234567800000000ULL)==0x1234567800000000ULL+i);
    }
    for (unsigned i=0;i<10000;i++) CHECK(p_mock_i12(1,2,3,4,5,6,7,8,9,10,11,i)==506+12ULL*i);
    printf("PASS %d ABI checks (17 signature cases, %u slot probes, 10000 repeated calls)\n",checks,(unsigned)MOCK_PAD_COUNT);
    return 0;
}
