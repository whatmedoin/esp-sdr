/* On-device equivalence checks. Called on SIMD core 1 before accepting work.
 * Reuse the duplicated window as scratch; no additional static SRAM. */
#include <assert.h>
#ifdef NDEBUG
#error "S31_FFT_VERIFY requires enabled assertions"
#endif
extern int s31_fft2r_sc16_reference(int16_t *, int, int16_t *);
static void s31_fft_verify(void) {
    uint32_t rng = 0x12345678u;
    for (unsigned n = 256; n <= S31_NMAX; n *= 2) {
        for (unsigned trial = 0; trial < 72; trial++) {
            for (unsigned j = 0; j < 2 * n; j++) {
                rng = rng * 1664525u + 1013904223u;
                int16_t x = (int16_t)(rng >> 16);
                if (trial == 0) x = 0;
                if (trial == 1) x = INT16_MIN;
                if (trial == 2) x = INT16_MAX;
                if (trial == 3) x = j & 1 ? INT16_MIN : INT16_MAX;
                if (trial == 4) x = j == 2 * n - 2 ? INT16_MAX : 0;
                if (trial == 5) x = (int16_t)lrintf(12000 * cosf(2 * M_PI * 17 * (j / 2) / n -
                                                               (j & 1) * M_PI / 2));
                s31_work.fft[j] = s31_win2[j] = x;
            }
            s31_fft2r_sc16_reference(s31_win2, n, dsps_fft_w_table_sc16);
            s31_fft2r_sc16_rnd(s31_work.fft, n, dsps_fft_w_table_sc16);
            assert(!memcmp(s31_win2, s31_work.fft, 2 * n * sizeof(int16_t)));
        }
    }
    for (unsigned n = 256; n <= S31_NMAX; n *= 2) {
        for (unsigned maximum = 0; maximum < 2; maximum++) {
            for (unsigned trial = 0; trial < 32; trial++) {
                for (unsigned j = 0; j < n; j++) {
                    rng = rng * 1664525u + 1013904223u;
                    int32_t re = (int16_t)rng, im = (int16_t)(rng >> 16);
                    if (trial == 0) re = im = INT16_MIN;
                    if (trial == 1) re = im = INT16_MAX;
                    if (trial == 2) re = im = 0;
                    s31_work.fft[2 * j] = re;
                    s31_work.fft[2 * j + 1] = im;
                    float old = trial < 4 ? 0 : (float)(rng & 0x7fffffffu) * (1u << (trial % 16));
                    s31_work.power[j] = old;
                    float p = (float)((uint32_t)(re * re) + (uint32_t)(im * im));
                    float expected = maximum ? fmaxf(old, p) : old + p;
                    memcpy(s31_win2 + 2 * j, &expected, sizeof(expected));
                }
                s31_accumulate(s31_work.fft, s31_work.power, n, maximum);
                assert(!memcmp(s31_win2, s31_work.power, n * sizeof(float)));
            }
        }
    }
    uint32_t raw[140] __attribute__((aligned(16)));
    int16_t win[256] __attribute__((aligned(16)));
    for (unsigned offset = 0; offset < 4; offset++) {
        for (unsigned trial = 0; trial < 8; trial++) {
            for (unsigned j = 0; j < 140; j++) {
                rng = rng * 1664525u + 1013904223u;
                raw[j] = rng;
                if (trial == 0) raw[j] = 0;
                if (trial == 1) raw[j] = 0x80080200u;
                if (trial == 2) raw[j] = 0xffffffffu;
            }
            for (unsigned j = 0; j < 128; j++) {
                rng = rng * 1664525u + 1013904223u;
                win[2 * j] = win[2 * j + 1] = trial < 3 ? 32767 : (rng >> 17);
            }
            for (unsigned groups = 1; groups <= 16; groups *= 2) {
                for (unsigned j = 0; j < groups * 8; j++) {
                    uint32_t w = raw[offset + j];
                    int32_t i = (int32_t)(w << 22) >> 22, q = (int32_t)(w << 12) >> 22;
                    s31_win2[2 * j] = (i * win[2 * j]) >> 9;
                    s31_win2[2 * j + 1] = (q * win[2 * j + 1]) >> 9;
                }
                s31_unpack_iq10_win(raw + offset, s31_work.fft, win, groups);
                assert(!memcmp(s31_win2, s31_work.fft, groups * 8 * 2 * sizeof(int16_t)));
            }
        }
    }
}
