"""
크롤러 01 — 선관위 Open API
- 후보자 기본 정보 (이름, 정당, 경력, 학력)
- 5대 선거공약 (제목 + 전문)
엔드포인트: apis.data.go.kr/9760000
"""
import requests
from utils.config import (
    NEC_API_KEY, ELECTION_ID, ELECTION_TYPE_CODE, CANDIDATES,
    NEC_PLEDGE_API, NEC_CANDIDATE_API,
)
from utils.db import upsert_candidate, insert_statement, get_candidate_id


def fetch_candidate_info():
    """후보자 정보 API → candidates 테이블 저장"""
    params = {
        "sgId":        ELECTION_ID,
        "sgTypecode":  ELECTION_TYPE_CODE,
        "sdName":      "서울특별시",
        "sggName":     "서울특별시",
        "pageNo":      "1",
        "numOfRows":   "20",
        "resultType":  "json",
        "serviceKey":  NEC_API_KEY,
    }
    resp = requests.get(NEC_CANDIDATE_API, params=params, timeout=10)
    resp.raise_for_status()

    items = resp.json()["response"]["body"]["items"]["item"]
    if isinstance(items, dict):
        items = [items]

    saved = 0
    for item in items:
        name = item.get("name", "")
        if name not in CANDIDATES:
            continue  # 주요 3당 외 후보 스킵

        upsert_candidate(
            name      = name,
            party     = item.get("jdName", ""),
            huboid    = item.get("huboid", ""),
            number    = int(item.get("giho", 0) or 0),
            career    = f"{item.get('career1','')}  /  {item.get('career2','')}",
            education = item.get("edu", ""),
        )
        print(f"    → {name} ({item.get('jdName')}) 등록")
        saved += 1

    return saved


def fetch_pledges():
    """5대 공약 API → statements 테이블 저장 (source_type='공약집')"""
    total = 0
    for name, info in CANDIDATES.items():
        candidate_id = get_candidate_id(name)
        if not candidate_id:
            print(f"    ⚠️  {name} 후보 미등록 — fetch_candidate_info() 먼저 실행")
            continue

        params = {
            "sgId":       ELECTION_ID,
            "sgTypecode": ELECTION_TYPE_CODE,
            "cnddtId":    info["huboid"],
            "pageNo":     "1",
            "numOfRows":  "10",
            "resultType": "json",
            "serviceKey": NEC_API_KEY,
        }
        resp = requests.get(NEC_PLEDGE_API, params=params, timeout=10)
        resp.raise_for_status()

        data = resp.json()["response"]["body"]["items"]["item"]
        item = data if isinstance(data, dict) else data[0]

        prms_cnt = int(item.get("prmsCnt", 0))
        count = 0

        for i in range(1, prms_cnt + 1):
            title   = item.get(f"prmsTitle{i}", "").strip()
            # API 응답 필드명이 prmmCont(오타?) vs prmsCont 두 가지 혼용
            content = (item.get(f"prmmCont{i}", "") or item.get(f"prmsCont{i}", "")).strip()
            realm   = (item.get(f"prmsRealmName{i}", "") or "기타").strip()

            if not content:
                continue

            stmt_id = insert_statement(
                candidate_id = candidate_id,
                topic        = realm,
                title        = title,
                content      = content,
                source_type  = "공약집",
                source_name  = f"선관위 5대 공약 — {name}",
                source_url   = f"https://policy.nec.go.kr",
                date         = ELECTION_ID[:4] + "-" + ELECTION_ID[4:6] + "-" + ELECTION_ID[6:],
            )
            if stmt_id:
                count += 1

        print(f"    → {name}: {count}/{prms_cnt}개 공약 저장")
        total += count

    return total


def run():
    print("\n[01] 선관위 Open API 수집")
    print("  후보자 정보 수집 중...")
    fetch_candidate_info()
    print("  선거공약 수집 중...")
    fetch_pledges()
    print("[01] 완료\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import init_db
    init_db()
    run()
