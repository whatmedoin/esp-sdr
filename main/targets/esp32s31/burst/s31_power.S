/* Exact IQ16 power, with independent bins scheduled across integer/FPU work.
 * void s31_accumulate(const int16_t *x, float *power, unsigned n, bool maximum)
 * n is a positive multiple of four; core 1 owns the hardware loop. */
    .text
    .align 4
    .global s31_accumulate
    .type s31_accumulate, @function

    .macro accumulate op, end
    esp.lp.setup 0,a2,\end
        lh t0,0(a0)
        lh t1,2(a0)
        lh t2,4(a0)
        lh t3,6(a0)
        lh t4,8(a0)
        lh t5,10(a0)
        lh t6,12(a0)
        lh a4,14(a0)
        mul t0,t0,t0
        mul t1,t1,t1
        mul t2,t2,t2
        mul t3,t3,t3
        mul t4,t4,t4
        mul t5,t5,t5
        mul t6,t6,t6
        mul a4,a4,a4
        add t0,t0,t1
        add t2,t2,t3
        add t4,t4,t5
        add t6,t6,a4
        fcvt.s.wu ft0,t0
        fcvt.s.wu ft1,t2
        fcvt.s.wu ft2,t4
        fcvt.s.wu ft3,t6
        flw ft4,0(a1)
        flw ft5,4(a1)
        flw ft6,8(a1)
        flw ft7,12(a1)
        \op ft0,ft4,ft0
        \op ft1,ft5,ft1
        \op ft2,ft6,ft2
        \op ft3,ft7,ft3
        fsw ft0,0(a1)
        fsw ft1,4(a1)
        fsw ft2,8(a1)
        fsw ft3,12(a1)
        addi a0,a0,16
\end:   addi a1,a1,16
    ret
    .endm

s31_accumulate:
    srli a2,a2,2
    bnez a3,.Lmaximum
    accumulate fadd.s, .Lmean_end
.Lmaximum:
    accumulate fmax.s, .Lmax_end
    .size s31_accumulate, . - s31_accumulate
