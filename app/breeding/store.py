"""系谱存储：租户级隔离 + SQLite 持久化。

改造前 `app/api/router.py` 用模块级单例持有唯一一个 ``PedigreeManager``，
导致两处问题：

1. **无租户隔离**——A 牧场登记的个体，B 牧场查询近交系数时也能看到；
2. **纯内存**——进程重启后全部系谱丢失，而事件/告警/租户都已落库。

本模块提供「按 tenant_id 分片的注册表 + 可替换存储」，
与 ``tenant_metadata_registry`` / ``tenant_registry`` 保持同一范式。
"""

import sqlite3
from pathlib import Path
from typing import Protocol

from app.breeding.pedigree import Animal, PedigreeManager

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pedigree_animals (
    tenant_id TEXT NOT NULL,
    animal_id TEXT NOT NULL,
    sire_id TEXT,
    dam_id TEXT,
    birth_date TEXT,
    PRIMARY KEY (tenant_id, animal_id)
)
"""


class PedigreeStore(Protocol):
    def load(self, tenant_id: str) -> list[Animal] | None: ...

    def save(self, tenant_id: str, animals: list[Animal]) -> None: ...


class InMemoryPedigreeStore:
    """内存实现，供无持久化场景与单元测试使用。"""

    def __init__(self) -> None:
        self._data: dict[str, list[Animal]] = {}

    def load(self, tenant_id: str) -> list[Animal] | None:
        stored = self._data.get(tenant_id)
        return list(stored) if stored is not None else None

    def save(self, tenant_id: str, animals: list[Animal]) -> None:
        self._data[tenant_id] = list(animals)


class SqlitePedigreeStore:
    """SQLite 持久实现：保存时整租户覆盖写，保证与内存态一致。"""

    def __init__(self, db_path: str = "data/pedigree.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.execute(_SCHEMA)
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_pedigree_tenant "
            "ON pedigree_animals(tenant_id)"
        )
        self._connection.commit()

    def load(self, tenant_id: str) -> list[Animal] | None:
        cursor = self._connection.execute(
            "SELECT animal_id, sire_id, dam_id, birth_date FROM pedigree_animals "
            "WHERE tenant_id = ? ORDER BY rowid",
            (tenant_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        return [
            Animal(
                animal_id=animal_id,
                sire_id=sire_id,
                dam_id=dam_id,
                birth_date=birth_date,
            )
            for animal_id, sire_id, dam_id, birth_date in rows
        ]

    def save(self, tenant_id: str, animals: list[Animal]) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM pedigree_animals WHERE tenant_id = ?", (tenant_id,)
            )
            self._connection.executemany(
                "INSERT INTO pedigree_animals "
                "(tenant_id, animal_id, sire_id, dam_id, birth_date) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        tenant_id,
                        animal.animal_id,
                        animal.sire_id,
                        animal.dam_id,
                        animal.birth_date,
                    )
                    for animal in animals
                ],
            )

    def close(self) -> None:
        self._connection.close()


class PedigreeRegistry:
    """租户级系谱注册表：每租户独享一个 :class:`PedigreeManager`。

    首次访问时按需从存储装载；写入路径调用 :meth:`persist` 落库。
    """

    def __init__(self, store: PedigreeStore | None = None) -> None:
        self._store: PedigreeStore = store or InMemoryPedigreeStore()
        self._managers: dict[str, PedigreeManager] = {}

    def bind_store(self, store: PedigreeStore | None) -> None:
        """绑定存储；传 None 时回落内存实现（lifespan 关停解绑用）。"""
        self._store = store or InMemoryPedigreeStore()
        self._managers.clear()

    def for_tenant(self, tenant_id: str) -> PedigreeManager:
        cached = self._managers.get(tenant_id)
        if cached is not None:
            return cached
        manager = PedigreeManager()
        for animal in self._store.load(tenant_id) or []:
            manager.add_animal(animal)
        self._managers[tenant_id] = manager
        return manager

    def persist(self, tenant_id: str) -> None:
        manager = self._managers.get(tenant_id)
        if manager is not None:
            self._store.save(tenant_id, manager.list_animals())

    def clear_cache(self) -> None:
        self._managers.clear()


pedigree_registry = PedigreeRegistry()
