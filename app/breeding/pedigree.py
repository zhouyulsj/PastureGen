from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel


class Animal(BaseModel):
    animal_id: str
    sire_id: str | None = None
    dam_id: str | None = None
    birth_date: str | None = None


class PedigreeCycleError(ValueError):
    """系谱存在环路（个体经由亲本链回到自身），无法进行遗传评估。"""


class PedigreeManager:
    """个体系谱与加性遗传关系矩阵。

    **顺序无关性**：个体登记顺序不受控（子代完全可能先于亲代录入），而加性
    关系矩阵的递推 ``a[i,j] = 0.5 * (a[sire,j] + a[dam,j])`` 要求亲代的行已
    算完。因此建矩阵前先做拓扑排序，保证"亲代必先于子代"再递推，
    使结果与登记顺序无关。
    """

    def __init__(self) -> None:
        self._animals: dict[str, Animal] = {}

    def add_animal(self, animal: Animal) -> None:
        self._animals[animal.animal_id] = animal

    def remove_animal(self, animal_id: str) -> bool:
        """移除个体（用于校验失败时回滚写入）。"""
        return self._animals.pop(animal_id, None) is not None

    def get_animal(self, animal_id: str) -> Animal | None:
        return self._animals.get(animal_id)

    def list_animals(self) -> list[Animal]:
        return list(self._animals.values())

    def validate_parents(self, animal: Animal) -> list[str]:
        problems: list[str] = []
        if animal.sire_id and animal.sire_id == animal.animal_id:
            problems.append("父本不能是个体自身")
        if animal.dam_id and animal.dam_id == animal.animal_id:
            problems.append("母本不能是个体自身")
        if animal.sire_id and animal.sire_id not in self._animals:
            problems.append(f"父本 {animal.sire_id} 不存在")
        if animal.dam_id and animal.dam_id not in self._animals:
            problems.append(f"母本 {animal.dam_id} 不存在")
        return problems

    def _known_parents(self, animal: Animal) -> list[str]:
        """返回在本群内可解析的亲代 ID（群外亲本按未知处理）。"""
        return [
            parent_id
            for parent_id in (animal.sire_id, animal.dam_id)
            if parent_id and parent_id in self._animals
        ]

    def _topological_order(self) -> list[str]:
        """Kahn 拓扑排序，返回"亲代必先于子代"的处理顺序。

        群体内出现环路时抛出 :class:`PedigreeCycleError`——显式失败优于
        静默算出一组错误的近交系数与育种值。
        """
        children: dict[str, list[str]] = {animal_id: [] for animal_id in self._animals}
        indegree: dict[str, int] = {}
        for animal_id, animal in self._animals.items():
            parents = self._known_parents(animal)
            indegree[animal_id] = len(parents)
            for parent_id in parents:
                children[parent_id].append(animal_id)

        queue = [animal_id for animal_id in self._animals if indegree[animal_id] == 0]
        order: list[str] = []
        while queue:
            node = queue.pop()
            order.append(node)
            for child in children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(self._animals):
            raise PedigreeCycleError("系谱存在环路，无法构建加性遗传关系矩阵")
        return order

    def detect_cycle(self) -> list[str]:
        """返回一条环路路径（用于报错展示），无环路返回空列表。"""
        graph: dict[str, list[str]] = defaultdict(list)
        for animal in self._animals.values():
            for parent_id in (animal.sire_id, animal.dam_id):
                if parent_id:
                    graph[animal.animal_id].append(parent_id)

        def dfs(node: str, path: list[str], visited: set[str]) -> list[str] | None:
            if node in path:
                return path[path.index(node) :]
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

    def build_additive_relationship_matrix(self) -> tuple[np.ndarray, list[str]]:
        """构建加性遗传关系矩阵 A（含近交系数）。

        返回 ``(A, ids)``，``ids`` 保持登记顺序以便与外部索引对齐。
        """
        ids = list(self._animals.keys())
        index = {animal_id: i for i, animal_id in enumerate(ids)}
        n = len(ids)
        a_matrix = np.zeros((n, n), dtype=float)

        completed: list[int] = []
        for animal_id in self._topological_order():
            i = index[animal_id]
            animal = self._animals[animal_id]
            sire = index[animal.sire_id] if animal.sire_id in index else None
            dam = index[animal.dam_id] if animal.dam_id in index else None

            if sire is None and dam is None:
                a_matrix[i, i] = 1.0  # 未知亲本：基础群个体
            else:
                # completed 中的个体均先于本个体处理，其行已最终确定
                for j in completed:
                    sire_value = a_matrix[sire, j] if sire is not None else 0.0
                    dam_value = a_matrix[dam, j] if dam is not None else 0.0
                    a_matrix[i, j] = a_matrix[j, i] = 0.5 * (sire_value + dam_value)
                if sire is not None and dam is not None:
                    a_matrix[i, i] = 1.0 + 0.5 * a_matrix[sire, dam]
                else:
                    a_matrix[i, i] = 1.0
            completed.append(i)

        return a_matrix, ids

    def inbreeding_coefficients(self) -> dict[str, float]:
        a_matrix, ids = self.build_additive_relationship_matrix()
        return {animal_id: a_matrix[i, i] - 1.0 for i, animal_id in enumerate(ids)}

    def build_additive_relationship_inverse(self) -> tuple[np.ndarray, list[str]]:
        """按 Henderson 递推规则构建 A⁻¹。

        该方法逐个体累加贡献、不引用已算出的 A 元素，因此**与登记顺序无关**。
        注：此处采用基础群非近交（F=0）的经典系数形式；当群体存在明显近交时
        需要用含 d_j 的一般式校正。
        """
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
