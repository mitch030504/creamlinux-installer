#include "mock.h"
#include <stdarg.h>
int32_t mock_int(int32_t a,int32_t b) { return a*2-b; }
uint64_t mock_u64(uint64_t a,uint64_t b) { return a^b; }
void *mock_ptr(void *p,uint64_t n) { return (char*)p+n; }
#define ARGS8(T) T a,T b,T c,T d,T e,T f,T g,T h
#define ARGS12(T) ARGS8(T),T i,T j,T k,T l
#define SUM8 (a+2*b+3*c+4*d+5*e+6*f+7*g+8*h)
#define SUM12 (SUM8+9*i+10*j+11*k+12*l)
uint64_t mock_i8(ARGS8(uint64_t)) { return SUM8; }
uint64_t mock_i12(ARGS12(uint64_t)) { return SUM12; }
float mock_float(float a,float b) { return a+2*b; }
double mock_double(double a,double b) { return a+3*b; }
double mock_f8(ARGS8(double)) { return SUM8; }
double mock_f12(ARGS12(double)) { return SUM12; }
double mock_mixed(uint64_t a,double b,uint64_t c,float d,void *p,uint64_t e,double f) { return a+b+c+d+(p!=0)+e+f-1; }
Pair mock_pair(uint64_t a,uint64_t b) { return (Pair){a,b}; }
Big mock_big(uint64_t a,uint64_t b) { return (Big){a,b,a+b,a^b}; }
Hfa mock_hfa(Hfa a,double b) { return (Hfa){a.a+b,a.b+b,a.c+b,a.d+b}; }
Vec mock_vector(Vec a,Vec b) { return a+b; }
double mock_variadic(int n,...) { va_list ap; va_start(ap,n); double r=0; for (int i=0;i<n;i++) r+=(i+1)*va_arg(ap,double); va_end(ap); return r; }
uint64_t mock_callback(uint64_t (*f)(uint64_t),uint64_t a) { return f(a)+1; }
uint64_t mock_indirect_arg(Big a,uint64_t b) { return a.a+2*a.b+3*a.c+4*a.d+b; }
