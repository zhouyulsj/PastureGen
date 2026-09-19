import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.breeding.blup import AnimalModelBlupSolver
from app.breeding.pedigree import Animal, PedigreeCycleError, PedigreeManager
from app.breeding.store import pedigree_registry
from app.device_ingestion import adapters  # noqa: F401
from app.device_ingestion.router import router as device_router
from app.genomics.genomic_selection import (
    GblupSolver,
    build_genomic_relationship_matrix,
)
from app.genomics.snp_quality_control import SnpQualityControl
from app.notification.router import router as dead_letter_router
from app.perception.router import router as alert_router
from app.tenant.context import get_current_tenant_id
from app.tenant.router import router as tenant_router

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
    """登记个体（按当前租户隔离，登记后落库）。

    校验分级：

    * **结构性错误**（个体自任亲本、引入系谱环路）→ 422，拒绝写入；
    * **非致命告警**（亲本尚未登记）→ 正常写入并在 ``parent_problems`` 中提示。
      缺失亲本是合法的建群场景，且 A 矩阵按"未知亲本"正确处理，
      亲代随后补录即可自动纳入计算。
    """
    tenant_id = get_current_tenant_id()
    manager = pedigree_registry.for_tenant(tenant_id)
    animal = Animal(**payload.model_dump())

    problems = manager.validate_parents(animal)
    fatal = [problem for problem in problems if "自身" in problem]
    if fatal:
        raise HTTPException(status_code=422, detail=fatal)

    manager.add_animal(animal)
    cycle = manager.detect_cycle()
    if cycle:
        manager.remove_animal(animal.animal_id)  # 回滚，不污染既有系谱
        raise HTTPException(
            status_code=422,
            detail={"message": "登记该个体将形成系谱环路", "cycle": cycle},
        )

    pedigree_registry.persist(tenant_id)
    return {"animal_id": animal.animal_id, "parent_problems": problems}


@api_router.get("/breeding/inbreeding", tags=["breeding"])
def inbreeding_coefficients() -> dict:
    manager = pedigree_registry.for_tenant(get_current_tenant_id())
    try:
        return manager.inbreeding_coefficients()
    except PedigreeCycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@api_router.post("/breeding/blup", tags=["breeding"])
def blup_evaluate(payload: BlupPayload) -> dict:
    """动物模型 BLUP 评估。

    表型向量按 ``animals`` 的顺序对齐（对应 ``Z = I`` 的设计），
    因此三个输入的长度必须一致，否则直接 422 而不是抛 numpy 内部异常。
    """
    n = len(payload.phenotypes)
    if n == 0:
        raise HTTPException(status_code=422, detail="phenotypes 不能为空")
    if len(payload.animals) != n:
        raise HTTPException(
            status_code=422,
            detail=(
                f"animals 与 phenotypes 长度必须一致："
                f"{len(payload.animals)} != {n}"
            ),
        )
    if payload.fixed_effect_levels is not None and len(payload.fixed_effect_levels) != n:
        raise HTTPException(
            status_code=422,
            detail=(
                f"fixed_effect_levels 与 phenotypes 长度必须一致："
                f"{len(payload.fixed_effect_levels)} != {n}"
            ),
        )

    manager = PedigreeManager()
    for animal_payload in payload.animals:
        manager.add_animal(Animal(**animal_payload.model_dump()))
    try:
        a_inverse, ids = manager.build_additive_relationship_inverse()
    except PedigreeCycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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
    n = len(payload.phenotypes)
    if n == 0:
        raise HTTPException(status_code=422, detail="phenotypes 不能为空")
    if len(payload.genotypes) != n:
        raise HTTPException(
            status_code=422,
            detail=(
                f"genotypes 个体数与 phenotypes 长度必须一致："
                f"{len(payload.genotypes)} != {n}"
            ),
        )
    genotypes = np.asarray(payload.genotypes, dtype=float)
    phenotypes = np.asarray(payload.phenotypes, dtype=float)
    g_matrix = build_genomic_relationship_matrix(genotypes)
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