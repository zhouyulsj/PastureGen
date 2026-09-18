from dataclasses import dataclass, field

import numpy as np


@dataclass
class QcReport:
    n_individuals: int
    n_snps: int
    call_rate_per_snp: np.ndarray = field(default_factory=lambda: np.array([]))
    maf_per_snp: np.ndarray = field(default_factory=lambda: np.array([]))
    kept_snp_indices: np.ndarray = field(default_factory=lambda: np.array([]))
    dropped_snp_count: int = 0


class SnpQualityControl:
    def __init__(self, maf_threshold: float = 0.01, call_rate_threshold: float = 0.9) -> None:
        self.maf_threshold = maf_threshold
        self.call_rate_threshold = call_rate_threshold

    def compute_call_rate(self, genotypes: np.ndarray) -> np.ndarray:
        return 1.0 - np.mean(np.isnan(genotypes), axis=0)

    def compute_maf(self, genotypes: np.ndarray) -> np.ndarray:
        allele_freq = np.nanmean(genotypes, axis=0) / 2.0
        return np.minimum(allele_freq, 1.0 - allele_freq)

    def run(self, genotypes: np.ndarray) -> QcReport:
        genotypes = np.asarray(genotypes, dtype=float)
        call_rate = self.compute_call_rate(genotypes)
        maf = self.compute_maf(genotypes)
        kept = np.where((call_rate >= self.call_rate_threshold) & (maf >= self.maf_threshold))[0]
        return QcReport(
            n_individuals=genotypes.shape[0],
            n_snps=genotypes.shape[1],
            call_rate_per_snp=call_rate,
            maf_per_snp=maf,
            kept_snp_indices=kept,
            dropped_snp_count=genotypes.shape[1] - len(kept),
        )