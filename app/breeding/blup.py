from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class GeneticEvaluationResult:
    breeding_values: np.ndarray
    reliabilities: np.ndarray | None = None
    fixed_effects: np.ndarray | None = None
    metadata: dict = field(default_factory=dict)


class GeneticSolver(ABC):
    solver_name: str = "generic"

    @abstractmethod
    def solve(
        self,
        phenotypes: np.ndarray,
        fixed_incidence_x: np.ndarray,
        random_incidence_z: np.ndarray,
        inverse_relationship: np.ndarray,
    ) -> GeneticEvaluationResult:
        raise NotImplementedError


def solve_mixed_model_equations(
    phenotypes: np.ndarray,
    fixed_incidence_x: np.ndarray,
    random_incidence_z: np.ndarray,
    inverse_relationship: np.ndarray,
    heritability: float = 0.3,
) -> GeneticEvaluationResult:
    y = np.asarray(phenotypes, dtype=float).reshape(-1, 1)
    x = np.asarray(fixed_incidence_x, dtype=float)
    z = np.asarray(random_incidence_z, dtype=float)
    a_inverse = np.asarray(inverse_relationship, dtype=float)

    heritability = max(min(heritability, 0.99), 0.01)
    sigma_a2 = heritability
    sigma_e2 = 1.0 - heritability
    lam = sigma_e2 / sigma_a2

    xtx = x.T @ x
    xtz = x.T @ z
    ztx = z.T @ x
    ztz = z.T @ z + a_inverse * lam

    lhs = np.vstack([np.hstack([xtx, xtz]), np.hstack([ztx, ztz])])
    rhs = np.vstack([x.T @ y, z.T @ y])

    solution = np.linalg.solve(lhs, rhs).reshape(-1)
    n_fixed = x.shape[1]
    fixed_effects = solution[:n_fixed]
    breeding_values = solution[n_fixed:]

    lhs_inverse = np.linalg.inv(lhs)
    prediction_error_variance = np.diag(lhs_inverse)[n_fixed:] * sigma_e2
    reliabilities = np.clip(1.0 - prediction_error_variance / sigma_a2, 0.0, 1.0)

    return GeneticEvaluationResult(
        breeding_values=breeding_values,
        reliabilities=reliabilities,
        fixed_effects=fixed_effects,
        metadata={"heritability": heritability, "lambda": lam},
    )


class AnimalModelBlupSolver(GeneticSolver):
    solver_name = "animal_model_blup"

    def __init__(self, heritability: float = 0.3) -> None:
        self.heritability = heritability

    def solve(
        self,
        phenotypes: np.ndarray,
        fixed_incidence_x: np.ndarray,
        random_incidence_z: np.ndarray,
        inverse_relationship: np.ndarray,
    ) -> GeneticEvaluationResult:
        return solve_mixed_model_equations(
            phenotypes,
            fixed_incidence_x,
            random_incidence_z,
            inverse_relationship,
            self.heritability,
        )