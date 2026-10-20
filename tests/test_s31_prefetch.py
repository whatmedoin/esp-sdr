"""Run the S31 prefetch ownership/wrap logic on the host with guarded buffers."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class S31Prefetch(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler unavailable')
    def test_complete_partial_revoked_and_wrapped_windows(self):
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>
#define S31_NMAX 2048u
#define S31_RING 16384u
#define S31_MASK (S31_RING-1)
typedef struct {
 unsigned bank,seq,first,count,phase,gain;uint64_t index;
} s31_job_t;
typedef struct {
 unsigned n,logn,rate,stride,upf,ms,unit;bool maximum,stats;
} s31_config_t;
static struct {_Atomic unsigned reader,bank_seq[2];} s31;
static uint32_t banks[2][S31_RING];
static int16_t guarded[2*S31_NMAX+16] __attribute__((aligned(16)));
static int16_t window[S31_NMAX],s31_win2[2*S31_NMAX];
static struct {int16_t *fft,*window;} s31_work={guarded+8,window};
static unsigned seed,checks,revoke_check,revoke_during,unpacked,held,expected_bank;
static bool recycled;
static uint32_t word(unsigned bank,unsigned j) {
 return (j*1664525u+1013904223u)^(seed*101u+bank*0x9e3779b9u);
}
static void recycle(void) {
 if(!atomic_load(&s31.bank_seq[expected_bank])&&!atomic_load(&s31.reader)&&!recycled){
  for(unsigned j=0;j<S31_RING;j++)banks[expected_bank][j]=0xa5c33c5au;
  recycled=true;
 }
}
static unsigned test_load(_Atomic unsigned *p) {
 if(p==&s31.bank_seq[expected_bank]) {
  assert(atomic_load(&s31.reader)==expected_bank+1);
  if(++checks==revoke_check)atomic_store(p,0);
 }
 return atomic_load(p);
}
static void test_store(_Atomic unsigned *p,unsigned value) {
 atomic_store(p,value);
 if(p==&s31.reader){
  if(value){assert(value==expected_bank+1);held=0;}
  else recycle();
 }
}
#define LOAD(p) test_load(&(p))
#define STORE(p,v) test_store(&(p),(v))
static volatile uint32_t *s31_bank(unsigned b){assert(b<2);return banks[b];}
static unsigned esp_cpu_get_cycle_count(void){static unsigned c;return ++c;}
static void s31_unpack_iq10_win(const uint32_t *src,int16_t *dst,const int16_t *win,unsigned groups) {
 assert(groups && atomic_load(&s31.reader)==expected_bank+1);
 assert(src>=banks[expected_bank] && src+groups*8+4<=banks[expected_bank]+S31_RING);
 assert(dst>=s31_work.fft && dst+groups*16<=s31_work.fft+2*S31_NMAX);
 held+=groups*8;assert(held<=128);
 for(unsigned j=0;j<groups*8;j++) {
  uint32_t w=src[j];int32_t i=(int32_t)(w<<22)>>22,q=(int32_t)(w<<12)>>22;
  dst[2*j]=(i*win[2*j])>>9;dst[2*j+1]=(q*win[2*j+1])>>9;
  if(revoke_during && ++unpacked==revoke_during)atomic_store(&s31.bank_seq[expected_bank],0);
 }
}
#include "s31_prefetch.h"
static void init(unsigned n,unsigned bank) {
 ++seed;expected_bank=bank;checks=unpacked=held=0;recycled=false;
 atomic_store(&s31.reader,0);atomic_store(&s31.bank_seq[bank],123);
 for(unsigned b=0;b<2;b++)for(unsigned j=0;j<S31_RING;j++)banks[b][j]=word(b,j);
 for(unsigned j=0;j<2*S31_NMAX+16;j++)guarded[j]=0x5a5a;
 for(unsigned j=0;j<n;j++)window[j]=s31_win2[2*j]=s31_win2[2*j+1]=(j*313u+seed*29u)&32767u;
}
static void check(unsigned n,unsigned count,unsigned first,unsigned phase,unsigned stride,unsigned bank,
                  unsigned fail_check,unsigned fail_during) {
 init(n,bank);revoke_check=fail_check;revoke_during=fail_during;
 s31_config_t cfg={.n=n,.stride=stride};s31_job_t job={.bank=bank,.seq=123,.first=first};
 unsigned times[8];for(unsigned j=0;j<8;j++)times[j]=0xbadbad;
 unsigned ready=s31_prefetch(&cfg,&job,phase,count,times);
 unsigned expected=count;
 if(fail_check && fail_check<=count*n/128)expected=(fail_check-1)/(n/128);
 if(fail_during)expected=((fail_during+127)/128*128)/n;
 assert(ready==expected && !atomic_load(&s31.reader));
 /* Reclaim before consuming results, as at revocation or run-end drain. */
 atomic_store(&s31.bank_seq[bank],0);recycle();assert(recycled);
 for(unsigned k=0;k<ready;k++) {
  assert(times[k]>0 && times[k]!=0xbadbad);
  for(unsigned j=0;j<n;j++) {
   unsigned at=(first+(phase+k*stride)*n+j)&S31_MASK;
   uint32_t w=word(bank,at);int32_t i=(int32_t)(w<<22)>>22,q=(int32_t)(w<<12)>>22;
   assert(s31_work.fft[2*(k*n+j)]==(i*window[j])>>9);
   assert(s31_work.fft[2*(k*n+j)+1]==(q*window[j])>>9);
  }
 }
 for(unsigned k=ready;k<8;k++)assert(times[k]==0xbadbad);
 for(unsigned j=0;j<8;j++)assert(guarded[j]==0x5a5a && guarded[2*S31_NMAX+8+j]==0x5a5a);
 for(unsigned j=2*count*n;j<2*S31_NMAX;j++)assert(s31_work.fft[j]==0x5a5a);
 /* Worker accounting after consuming every complete private window. */
 unsigned blocks=phase+count*stride,block=phase+ready*stride;
 unsigned skipped=ready<count?(blocks-block+stride-1)/stride:0;
 assert(ready+skipped==count);
}
int main(void) {
 const unsigned firsts[]={0,1,3,127,S31_RING-1,S31_RING-4,S31_RING-127,S31_RING-256};
 for(unsigned n=256;n<=S31_NMAX;n*=2) {
  for(unsigned count=1;count<=S31_NMAX/n;count++) {
   for(unsigned b=0;b<2;b++)for(unsigned stride=1;stride<=3;stride+=2)
    for(unsigned phase=0;phase<=2;phase+=2)
     for(unsigned f=0;f<sizeof(firsts)/sizeof(*firsts);f++)check(n,count,firsts[f],phase,stride,b,0,0);
   for(unsigned fail=1;fail<=count*n/128+1;fail++)check(n,count,0,0,1,0,fail,0);
   for(unsigned at=128;at<=count*n;at+=128)check(n,count,0,0,1,1,0,at);
  }
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'prefetch.c'
            src.write_text(source)
            exe = Path(tmp) / 'prefetch'
            subprocess.run(['cc', '-std=gnu11', '-O2', '-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all',
                            '-I' + str(ROOT / 'main/targets/esp32s31/burst'),
                            str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
