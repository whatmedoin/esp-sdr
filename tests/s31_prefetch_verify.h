/* Core-1 numeric checks while RF capture is stopped. No additional static buffers. */
static uint32_t s31_prefetch_word(unsigned at) {
    return at * 1664525u + 1013904223u;
}
static void s31_prefetch_verify(void) {
    unsigned saved_mode = spectrum_dc_mode;
    const unsigned firsts[] = {0, S31_RING - 4, S31_RING - 127};
    for (unsigned n = 256; n <= 1024; n *= 2) {
        for (unsigned count = 1; count <= S31_NMAX / n; count++) {
            for (unsigned bank = 0; bank < 2; bank++) {
                for (unsigned f = 0; f < sizeof(firsts) / sizeof(*firsts); f++) {
                    for (unsigned mode = 0; mode < 2; mode++) {
                        for (unsigned maximum = 0; maximum < 2; maximum++) {
                            spectrum_dc_mode = mode;
                            s31_config_t cfg = {.n = n, .stride = 1, .maximum = maximum};
                            s31_job_t job = {.bank = bank, .seq = 123, .first = firsts[f]};
                            for (unsigned j = 0; j < S31_RING; j++)
                                s31_bank(bank)[j] = s31_prefetch_word(j);
                            for (unsigned j = 0; j < n; j++) {
                                s31_work.window[j] = (j * 1031u + 173u) & 32767u;
                                s31_win2[2 * j] = s31_win2[2 * j + 1] = s31_work.window[j];
                            }
                            STORE(s31.bank_seq[bank], job.seq);
                            unsigned copy_cycles[8];
                            unsigned ready = s31_prefetch(&cfg, &job, 0, count, copy_cycles);
                            assert(ready == count && !LOAD(s31.reader));
                            /* All DSP must remain independent of the reclaimed bank. */
                            STORE(s31.bank_seq[bank], 0);
                            s31_mark(bank, 0, S31_RING);
                            memset(s31_work.power, 0, 2 * n * sizeof(float));
                            spectrum_dc_t dc = {0}, reference_dc = {0};
                            for (unsigned k = 0; k < ready; k++) {
                                int16_t *x = s31_work.fft + 2 * k * n;
                                for (unsigned j = 0; j < n; j++) {
                                    uint32_t w = s31_prefetch_word((job.first + k * n + j) & S31_MASK);
                                    int32_t i = (int32_t)(w << 22) >> 22, q = (int32_t)(w << 12) >> 22;
                                    s31_win2[2 * j] = (i * s31_work.window[j]) >> 9;
                                    s31_win2[2 * j + 1] = (q * s31_work.window[j]) >> 9;
                                }
                                assert(!memcmp(x, s31_win2, 2 * n * sizeof(int16_t)));
                                s31_fft2r_sc16_rnd(x, n, dsps_fft_w_table_sc16);
                                s31_fft2r_sc16_reference(s31_win2, n, dsps_fft_w_table_sc16);
                                spectrum_dc_apply(&dc, x, n);
                                spectrum_dc_apply(&reference_dc, s31_win2, n);
                                assert(!memcmp(x, s31_win2, 2 * n * sizeof(int16_t)));
                                s31_accumulate(x, s31_work.power, n, maximum);
                                s31_accumulate(s31_win2, s31_work.power + n, n, maximum);
                            }
                            assert(dc.re == reference_dc.re && dc.im == reference_dc.im &&
                                   dc.ready == reference_dc.ready);
                            assert(!memcmp(s31_work.power, s31_work.power + n, n * sizeof(float)));
                            assert(s31_prefetch(&cfg, &job, 0, count, copy_cycles) == 0);
                            assert(!LOAD(s31.reader));
                        }
                    }
                }
            }
        }
    }
    spectrum_dc_mode = saved_mode;
    memset(s31_work.power, 0, S31_NMAX * sizeof(float));
}
