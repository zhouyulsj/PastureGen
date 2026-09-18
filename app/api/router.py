import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from app.breeding.blup import AnimalModelBlupSolver
from app.breeding.pedigree import Animal, PedigreeManager
from app.device_ingestion import adapters  # noqa: F401
from app.device_ingestion.router import router as device_router
from app.genomics.genomic_selection import (
    GblupSolver,
    build_genomic_relationship_matrix,
)
from app.genomics.snp_quality_control import SnpQualityControl
from app.notification.router import router as dead_letter_router
from app.perception.router import router as alert_router
from app.tenant.router import router as tenant_router

pedigree_manager = PedigreeManager()

api_router = APIRouter()
api_router.include_router(device_router)
api_router.include_router(tenant_router)
api_router.include_router(alert_router)
api_router.include_router(dead_letter_router)


class AnimalPayload(BaseModel):
    animal_id: str
    sire_id: str | None = None
    dam_id: str | None = None


class GenotypePayload(BaseModel):
    genotypes: list[list[float]]


class GblupPayload(BaseModel):
    genotypes: list[list[float]]
    phenotypes: list[float]
    heritability: float = 0.3


class BlupPayload(BaseModel):
    animals: list[AnimalPayload]
    phenotypes: list[float]
    fixed_effect_levels: list[int] | None = None
    heritability: float = 0.3


def _one_hot_encode(levels: list[int], n: int) -> np.ndarray:
    unique = sorted(set(levels))
    column_index = {level: i for i, level in enumerate(unique)}
    matrix = np.zeros((n, len(unique)), dtype=float)
    for row, level in enumerate(levels):
        matrix[row, column_index[level]] = 1.0
    return matrix


@api_router.post("/breeding/animals", tags=["breeding"])
def register_animal(payload: AnimalPayload) -> dict:
    animal = Animal(**payload.model_dump())
    problems = pedigree_manager.validate_parents(animal)
    pedigree_manager.add_animal(animal)
    return {"animal_id": animal.animal_id, "parent_problems": problems}


@api_router.get("/breeding/inbreeding", tags=["breeding"])
def inbreeding_coefficients() -> dict:
    return pedigree_manager.inbreeding_coefficients()


@api_router.post("/breeding/blup", tags=["breeding"])
def blup_evaluate(payload: BlupPayload) -> dict:
    manager = PedigreeManager()
    for animal_payload in payload.animals:
        manager.add_animal(Animal(**animal_payload.model_dump()))
    a_inverse, ids = manager.build_additive_relationship_inverse()

    n = len(payload.phenotypes)
    fixed_incidence_x = np.ones((n, 1), dtype=float)
    if payload.fixed_effect_levels is not None:
        fixed_incidence_x = _one_hot_encode(payload.fixed_effect_levels, n)
    random_incidence_z = np.eye(n)

    result = AnimalModelBlupSolver(payload.heritability).solve(
        np.asarray(payload.phenotypes, dtype=float),
        fixed_incidence_x,
        random_incidence_z,
        a_inverse,
    )
    reliability_list = result.reliabilities.tolist() if result.reliabilities is not None else []
    return {
        "breeding_values": dict(zip(ids, result.breeding_values.tolist())),
        "reliabilities": dict(zip(ids, reliability_list)),
        "fixed_effects": result.fixed_effects.tolist(),
        "metadata": result.metadata,
    }


@api_router.post("/genomics/quality-control", tags=["genomics"])
def quality_control(payload: GenotypePayload) -> dict:
    genotypes = np.asarray(payload.genotypes, dtype=float)
    report = SnpQualityControl().run(genotypes)
    return {
        "n_individuals": report.n_individuals,
        "n_snps": report.n_snps,
        "dropped_snp_count": report.dropped_snp_count,
        "kept_snp_indices": report.kept_snp_indices.tolist(),
    }


@api_router.post("/genomics/gblup", tags=["genomics"])
def gblup_evaluate(payload: GblupPayload) -> dict:
    genotypes = np.asarray(payload.genotypes, dtype=float)
    phenotypes = np.asarray(payload.phenotypes, dtype=float)
    g_matrix = build_genomic_relationship_matrix(genotypes)
    n = len(phenotypes)
    fixed_incidence_x = np.ones((n, 1), dtype=float)
    random_incidence_z = np.eye(n)
    result = GblupSolver(payload.heritability).solve(
        phenotypes, fixed_incidence_x, random_incidence_z, g_matrix
    )
    reliability_list = result.reliabilities.tolist() if result.reliabilities is not None else []
    return {
        "breeding_values": result.breeding_values.tolist(),
        "reliabilities": reliability_list,
        "fixed_effects": result.fixed_effects.tolist(),
        "metadata": result.metadata,
    }