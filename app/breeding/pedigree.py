from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel


class Animal(BaseModel):
    animal_id: str
    sire_id: str | None = None
    dam_id: str | None = None
    birth_date: str | None = None


class PedigreeManager:
    def __init__(self) -> None:
        self._animals: dict[str, Animal] = {}

    def add_animal(self, animal: Animal) -> None:
        self._animals[animal.animal_id] = animal

    def get_animal(self, animal_id: str) -> Animal | None:
        return self._animals.get(animal_id)

    def validate_parents(self, animal: Animal) -> list[str]:
        problems: list[str] = []
        if animal.sire_id and animal.sire_id not in self._animals:
            problems.append(f"父本 {animal.sire_id} 不存在")
        if animal.dam_id and animal.dam_id not in self._animals:
            problems.append(f"母本 {animal.dam_id} 不存在")
        return problems

    def detect_cycle(self) -> list[str]:
        graph: dict[str, list[str]] = defaultdict(list)
        for animal in self._animals.values():
            for parent_id in (animal.sire_id, animal.dam_id):
                if parent_id:
                    graph[animal.animal_id].append(parent_id)

        def dfs(node: str, path: list[str], visited: set[str]) -> list[str] | None:
            if node in path:
                return path[path.index(node):]
            if node in visited:
                return None
            visited.add(node)
            for parent in graph[node]:
                result = dfs(parent, path + [node], visited)
                if result:
                    return result
            return None

        for animal_id in self._animals:
            cycle = dfs(animal_id, [], set())
            if cycle:
                return cycle
        return []

    def build_additive_relationship_matrix(self) -> np.ndarray:
        ids = list(self._animals.keys())
        index = {animal_id: i for i, animal_id in enumerate(ids)}
        n = len(ids)
        a_matrix = np.zeros((n, n), dtype=float)
        for i, animal_id in enumerate(ids):
            animal = self._animals[animal_id]
            if animal.sire_id and animal.dam_id and animal.sire_id in index and animal.dam_id in index:
                s = index[animal.sire_id]
                d = index[animal.dam_id]
                for j in range(i):
                    a_matrix[i, j] = a_matrix[j, i] = 0.5 * (a_matrix[s, j] + a_matrix[d, j])
                a_matrix[i, i] = 1.0 + 0.5 * a_matrix[s, d]
            else:
                a_matrix[i, i] = 1.0
        return a_matrix, ids

    def inbreeding_coefficients(self) -> dict[str, float]:
        a_matrix, ids = self.build_additive_relationship_matrix()
        return {animal_id: a_matrix[i, i] - 1.0 for i, animal_id in enumerate(ids)}
    def build_additive_relationship_inverse(self) -> tuple[np.ndarray, list[str]]:
        ids = list(self._animals.keys())
        index = {animal_id: i for i, animal_id in enumerate(ids)}
        n = len(ids)
        a_inverse = np.zeros((n, n), dtype=float)
        for i, animal_id in enumerate(ids):
            animal = self._animals[animal_id]
            sire = index.get(animal.sire_id) if animal.sire_id else None
            dam = index.get(animal.dam_id) if animal.dam_id else None
            if sire is None and dam is None:
                a_inverse[i, i] += 1.0
            elif sire is not None and dam is None:
                a_inverse[i, i] += 4.0 / 3.0
                a_inverse[i, sire] += -2.0 / 3.0
                a_inverse[sire, i] += -2.0 / 3.0
                a_inverse[sire, sire] += 1.0 / 3.0
            elif sire is None and dam is not None:
                a_inverse[i, i] += 4.0 / 3.0
                a_inverse[i, dam] += -2.0 / 3.0
                a_inverse[dam, i] += -2.0 / 3.0
                a_inverse[dam, dam] += 1.0 / 3.0
            else:
                s = sire
                d = dam
                a_inverse[i, i] += 2.0
                a_inverse[i, s] += -1.0
                a_inverse[s, i] += -1.0
                a_inverse[i, d] += -1.0
                a_inverse[d, i] += -1.0
                a_inverse[s, s] += 0.5
                a_inverse[d, d] += 0.5
                a_inverse[s, d] += 0.5
                a_inverse[d, s] += 0.5
        return a_inverse, ids