#pragma once
#include <stdint.h>
typedef struct { uint64_t a,b; } Pair;
typedef struct { uint64_t a,b,c,d; } Big;
typedef struct { double a,b,c,d; } Hfa;
typedef uint64_t Vec __attribute__((vector_size(16)));
#define API __attribute__((visibility("default"),noinline))
API int32_t mock_int(int32_t a, int32_t b);
API uint64_t mock_u64(uint64_t a, uint64_t b);
API void *mock_ptr(void *p, uint64_t offset);
API uint64_t mock_i8(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
API uint64_t mock_i12(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
API float mock_float(float,float);
API double mock_double(double,double);
API double mock_f8(double,double,double,double,double,double,double,double);
API double mock_f12(double,double,double,double,double,double,double,double,double,double,double,double);
API double mock_mixed(uint64_t,double,uint64_t,float,void*,uint64_t,double);
API Pair mock_pair(uint64_t,uint64_t);
API Big mock_big(uint64_t,uint64_t);
API Hfa mock_hfa(Hfa,double);
API Vec mock_vector(Vec,Vec);
API double mock_variadic(int,...);
API uint64_t mock_callback(uint64_t (*)(uint64_t),uint64_t);
API uint64_t mock_indirect_arg(Big,uint64_t);
