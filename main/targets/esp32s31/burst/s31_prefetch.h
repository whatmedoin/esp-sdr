/* Copy complete windows into disjoint slices of the existing private FFT buffer.
 * count * cfg->n must not exceed S31_NMAX. An incomplete final window is excluded. */
static unsigned s31_prefetch(const s31_config_t *cfg, const s31_job_t *job, unsigned block,
                             unsigned count, unsigned *copy_cycles) {
    unsigned ready = 0;
    for (; ready < count; ready++) {
        unsigned start = esp_cpu_get_cycle_count();
        unsigned at = job->first + (block + ready * cfg->stride) * cfg->n;
        int16_t *dst = s31_work.fft + 2 * ready * cfg->n;
        for (unsigned from = 0; from < cfg->n; from += 128) {
            /* Paired with revocation on core 0. Keep each reader hold bounded. */
            STORE(s31.reader, job->bank + 1);
            atomic_thread_fence(memory_order_seq_cst);
            if (LOAD(s31.bank_seq[job->bank]) != job->seq) {
                STORE(s31.reader, 0);
                return ready;
            }
            unsigned to = from + 128, j = from;
            while (j < to) {
                unsigned first = (at + j) & S31_MASK;
                unsigned available = first + 4 < S31_RING ? S31_RING - first - 4 : 0;
                unsigned span = to - j < available ? to - j : available, bulk = span & ~7u;
                if (bulk) {
                    s31_unpack_iq10_win((const uint32_t *)s31_bank(job->bank) + first,
                                        dst + 2 * j, s31_win2 + 2 * j, bulk / 8);
                    j += bulk;
                } else {
                    unsigned end = j + 8 < to ? j + 8 : to;
                    for (; j < end; j++) {
                        uint32_t w = s31_bank(job->bank)[(at + j) & S31_MASK];
                        int32_t i = (int32_t)(w << 22) >> 22, q = (int32_t)(w << 12) >> 22;
                        dst[2 * j] = (i * s31_work.window[j]) >> 9;
                        dst[2 * j + 1] = (q * s31_work.window[j]) >> 9;
                    }
                }
            }
            STORE(s31.reader, 0);
        }
        copy_cycles[ready] = esp_cpu_get_cycle_count() - start;
    }
    return ready;
}
