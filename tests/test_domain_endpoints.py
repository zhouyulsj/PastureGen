"""领域端点基线：设备采集 / webhook、育种系谱与 BLUP、基因组 QC 与 gBLUP。"""

import uuid


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_adapters(client):
    adapters = client.get("/api/v1/devices/adapters").json()
    types = [a["type"] for a in adapters]
    assert "mock_rfid" in types
    assert "http_scale" in types
    assert "http_camera" in types


def test_collect_and_persist(client):
    resp = client.post(
        "/api/v1/devices/collect",
        json={"adapter_type": "mock_rfid", "animal_id": "CN-0001"},
    )
    assert resp.status_code == 200
    collected = resp.json()["collected"]
    assert collected and collected[0]["metric"] == "rfid_presence"
    events = client.get("/api/v1/devices/events").json()
    assert len(events) >= len(collected)


def test_webhook_scale_and_camera(client):
    scale = client.post(
        "/api/v1/devices/webhook/http_scale",
        json={"animal_id": "CN-0001", "weight_kg": 650.5},
    )
    assert scale.status_code == 200
    assert scale.json()["accepted"] is True
    camera = client.post(
        "/api/v1/devices/webhook/http_camera", json={"count": 128}
    )
    assert camera.status_code == 200
    assert camera.json()["accepted"] is True


def test_breeding_inbreeding(client):
    # 用唯一后缀避免模块级系谱单例在跨用例时的 id 冲突
    uid = uuid.uuid4().hex[:6]
    sire, dam = f"S-{uid}", f"D-{uid}"
    child = f"A-{uid}"
    for animal in [
        {"animal_id": sire},
        {"animal_id": dam},
        {"animal_id": child, "sire_id": sire, "dam_id": dam},
    ]:
        resp = client.post("/api/v1/breeding/animals", json=animal)
        assert resp.status_code == 200
    coefficients = client.get("/api/v1/breeding/inbreeding").json()
    assert child in coefficients
    assert coefficients[child] == 0.0  # 双亲无亲缘，近交系数为 0


def test_breeding_blup(client):
    payload = {
        "animals": [
            {"animal_id": "S"},
            {"animal_id": "D"},
            {"animal_id": "A", "sire_id": "S", "dam_id": "D"},
            {"animal_id": "B"},
            {"animal_id": "C"},
            {"animal_id": "E", "sire_id": "B", "dam_id": "C"},
        ],
        "phenotypes": [10.0, 12.0, 15.0, 8.0, 9.0, 14.0],
        "fixed_effect_levels": [0, 0, 0, 1, 1, 1],
        "heritability": 0.3,
    }
    resp = client.post("/api/v1/breeding/blup", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert set(result["breeding_values"]) == {"S", "D", "A", "B", "C", "E"}
    assert set(result["reliabilities"]) == set(result["breeding_values"])
    # 表型高的个体应有更高的育种值（A:15 vs B:8）
    assert result["breeding_values"]["A"] > result["breeding_values"]["B"]


def test_genomics_quality_control(client):
    resp = client.post(
        "/api/v1/genomics/quality-control",
        json={"genotypes": [[0, 1, 2], [2, 1, 0], [1, 1, 1]]},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["n_individuals"] == 3
    assert report["n_snps"] == 3
    assert len(report["kept_snp_indices"]) + report["dropped_snp_count"] == 3


def test_genomics_gblup(client):
    resp = client.post(
        "/api/v1/genomics/gblup",
        json={
            "genotypes": [[0, 2], [2, 0]],
            "phenotypes": [1.0, 2.0],
            "heritability": 0.3,
        },
    )
    assert resp.status_code == 200
    result = resp.json()
    assert len(result["breeding_values"]) == 2
    assert "metadata" in result
