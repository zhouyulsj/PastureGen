import numpy as np

from app.breeding.blup import GeneticEvaluationResult, GeneticSolver, solve_mixed_model_equations


def build_genomic_relationship_matrix(genotypes: np.ndarray) -> np.ndarray:
    genotypes = np.asarray(genotypes, dtype=float)
    allele_freq = np.nanmean(genotypes, axis=0) / 2.0
    p_matrix = 2.0 * allele_freq
    centered = np.where(np.isnan(genotypes), 0.0, genotypes - p_matrix)
    denominator = 2.0 * np.sum(allele_freq * (1.0 - allele_freq))
    if denominator == 0.0:
        denominator = 1.0
    return centered @ centered.T / denominator


def build_h_matrix(
    a_matrix: np.ndarray, g_matrix: np.ndarray, genotyped_indices: np.ndarray
) -> np.ndarray:
    h_matrix = a_matrix.copy()
    idx = np.asarray(genotyped_indices, dtype=int)
    h_block = g_matrix - a_matrix[np.ix_(idx, idx)]
    h_matrix[np.ix_(idx, idx)] += h_block
    return h_matrix


class GblupSolver(GeneticSolver):
    solver_name = "gblup"

    def __init__(self, heritability: float = 0.3) -> None:
        self.heritability = heritability

    def solve(
        self,
        phenotypes: np.ndarray,
        fixed_incidence_x: np.ndarray,
        random_incidence_z: np.ndarray,
        relationship_matrix: np.ndarray,
    ) -> GeneticEvaluationResult:
        g_matrix = self._blend_to_positive_definite(relationship_matrix)
        g_inverse = np.linalg.inv(g_matrix)
        return solve_mixed_model_equations(
            phenotypes,
            fixed_incidence_x,
            random_incidence_z,
            g_inverse,
            self.heritability,
        )

    @staticmethod
    def _blend_to_positive_definite(matrix: np.ndarray) -> np.ndarray:
        n = matrix.shape[0]
        return 0.99 * matrix + 0.01 * np.eye(n)


class SsGblupSolver(GeneticSolver):
    solver_name = "ssgblup"

    def __init__(self, heritability: float = 0.3) -> None:
        self.heritability = heritability

    def solve(
        self,
        phenotypes: np.ndarray,
        fixed_incidence_x: np.ndarray,
        random_incidence_z: np.ndarray,
        h_matrix: np.ndarray,
    ) -> GeneticEvaluationResult:
        h_matrix = GblupSolver._blend_to_positive_definite(h_matrix)
        h_inverse = np.linalg.inv(h_matrix)
        return solve_mixed_model_equations(
            phenotypes,
            fixed_incidence_x,
            random_incidence_z,
            h_inverse,
            self.heritability,
        )