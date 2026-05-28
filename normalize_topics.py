"""
Topic 정규화 스크립트
Step 1: 비표준 topic 값 → 표준값으로 직접 치환
Step 2: topic='기타' 레코드를 제목+내용 키워드 매칭으로 재분류
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db import get_connection

# ─────────────────────────────────────────────────────────
# 표준 topic 목록
# ─────────────────────────────────────────────────────────
VALID_TOPICS = {
    "주택/부동산", "교통/인프라", "경제/일자리", "교육",
    "환경/기후", "복지", "안전", "행정/거버넌스",
    "문화/관광", "청년", "기타",
}

# ─────────────────────────────────────────────────────────
# Step 1: 명백한 비표준값 → 표준값 매핑
# ─────────────────────────────────────────────────────────
DIRECT_REMAP = {
    "주택1":      "주택/부동산",
    "주택2":      "주택/부동산",
    "교통":       "교통/인프라",
    "산업일자리": "경제/일자리",
    "디지털/AI":  "행정/거버넌스",
    "종합":       "기타",        # 후속 Step 2에서 재분류 대상이 됨
}

# ─────────────────────────────────────────────────────────
# Step 2: 키워드 기반 재분류
# ─────────────────────────────────────────────────────────

# 제목에서 우선 매칭 (긴 문자열 먼저)
TITLE_OVERRIDES = [
    ("AI행정혁신",      "행정/거버넌스"),
    ("AI행정",          "행정/거버넌스"),
    ("AI 행정",         "행정/거버넌스"),
    ("규제 혁신",       "행정/거버넌스"),
    ("규제혁신",        "행정/거버넌스"),
    ("시민·관변단체",   "행정/거버넌스"),
    ("복지의 재설계",   "복지"),
    ("복지 재설계",     "복지"),
    ("1인 가구",        "주택/부동산"),
    ("압도적 주택공급", "주택/부동산"),
    ("주거이동 안전망", "주택/부동산"),
    ("교통 대전환",     "교통/인프라"),
    ("약자와의 동행",   "복지"),
    ("통근도시",        "교통/인프라"),
    ("공간 대전환",     "행정/거버넌스"),
    ("청년창업",        "경제/일자리"),
    ("아이돌봄",        "복지"),
    ("시니어",          "복지"),
    ("바로 공약 ③ 교통", "교통/인프라"),
    ("바로 공약 ① AI",  "행정/거버넌스"),
    ("의료",            "복지"),
    ("재개발·재건축",   "주택/부동산"),
    ("재개발 재건축",   "주택/부동산"),
    ("고용 정책",       "경제/일자리"),
    ("고용정책",        "경제/일자리"),
    ("신통기획",        "주택/부동산"),
    ("서소문 고가도로", "안전"),
    ("붕괴사고",        "안전"),
    ("재난대책",        "안전"),
    ("안전하게",        "안전"),
    ("폭행 판결",       "행정/거버넌스"),  # 정치 이슈 → 행정
    ("이직합니다",      None),             # 비정책 → 기타 유지
    ("노래",            None),
    ("커버",            None),
    ("라이브",          None),
    ("식탁",            None),             # 서울식탁 시리즈 → 기타 유지
    ("로고송",          None),
    ("뮤비",            None),
    ("강연",            None),
    ("고려대",          None),
]

# 제목+내용 키워드 매칭 (짧은 키워드, 제목 우선)
KEYWORD_MAP = [
    # 주택/부동산
    ("재건축",    "주택/부동산"),
    ("재개발",    "주택/부동산"),
    ("주택공급",  "주택/부동산"),
    ("주거",      "주택/부동산"),
    ("임대",      "주택/부동산"),
    ("정비사업",  "주택/부동산"),
    ("신통기획",  "주택/부동산"),
    ("분양",      "주택/부동산"),
    ("1인가구",   "주택/부동산"),
    ("역세권",    "주택/부동산"),
    # 교통/인프라
    ("교통",      "교통/인프라"),
    ("지하철",    "교통/인프라"),
    ("버스",      "교통/인프라"),
    ("GTX",       "교통/인프라"),
    ("통근",      "교통/인프라"),
    ("따릉이",    "교통/인프라"),
    ("철도",      "교통/인프라"),
    ("도로",      "교통/인프라"),
    # 복지
    ("복지",      "복지"),
    ("의료",      "복지"),
    ("돌봄",      "복지"),
    ("어르신",    "복지"),
    ("장애",      "복지"),
    ("연금",      "복지"),
    ("건강",      "복지"),
    ("노인",      "복지"),
    ("임산부",    "복지"),
    # 교육
    ("교육",      "교육"),
    ("학교",      "교육"),
    ("서울런",    "교육"),
    ("학생",      "교육"),
    # 경제/일자리
    ("일자리",    "경제/일자리"),
    ("창업",      "경제/일자리"),
    ("고용",      "경제/일자리"),
    ("기업",      "경제/일자리"),
    ("경제",      "경제/일자리"),
    ("소상공인",  "경제/일자리"),
    ("노동",      "경제/일자리"),
    ("플랫폼 노동", "경제/일자리"),
    # 환경/기후
    ("기후",      "환경/기후"),
    ("환경",      "환경/기후"),
    ("탄소",      "환경/기후"),
    ("녹지",      "환경/기후"),
    ("생태",      "환경/기후"),
    ("에너지",    "환경/기후"),
    # 안전
    ("안전",      "안전"),
    ("재난",      "안전"),
    ("붕괴",      "안전"),
    ("소방",      "안전"),
    ("싱크홀",    "안전"),
    # 문화/관광
    ("문화",      "문화/관광"),
    ("관광",      "문화/관광"),
    ("예술",      "문화/관광"),
    ("공연",      "문화/관광"),
    ("축제",      "문화/관광"),
    # 청년
    ("청년",      "청년"),
    # 행정/거버넌스
    ("AI",        "행정/거버넌스"),
    ("디지털",    "행정/거버넌스"),
    ("행정",      "행정/거버넌스"),
    ("규제",      "행정/거버넌스"),
    ("공약 검증", "행정/거버넌스"),
    ("공약검증",  "행정/거버넌스"),
    ("예산",      "행정/거버넌스"),
]


def guess_topic_from_text(title: str, content: str) -> str | None:
    """제목 + 내용에서 topic 추측. 확신 없으면 None 반환."""
    combined_title = (title or "").strip()
    combined_content = ((content or "")[:400]).strip()

    # 1) 제목 override 우선 (순서 중요)
    for keyword, topic in TITLE_OVERRIDES:
        if keyword in combined_title:
            return topic  # None이면 '기타' 유지

    # 2) 제목에서 키워드 매칭
    for keyword, topic in KEYWORD_MAP:
        if keyword in combined_title:
            return topic

    # 3) 내용에서 키워드 매칭
    for keyword, topic in KEYWORD_MAP:
        if keyword in combined_content:
            return topic

    return None  # 분류 불가 → '기타' 유지


# ─────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────
def run():
    conn = get_connection()

    # ── Step 1 ─────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  Step 1: 비표준 topic 직접 치환")
    print("=" * 55)

    step1_total = 0
    for old_topic, new_topic in DIRECT_REMAP.items():
        rows = conn.execute(
            "SELECT id FROM statements WHERE topic=?", (old_topic,)
        ).fetchall()
        if rows:
            conn.execute(
                "UPDATE statements SET topic=? WHERE topic=?", (new_topic, old_topic)
            )
            print(f"  '{old_topic}' → '{new_topic}': {len(rows)}건")
            step1_total += len(rows)

    conn.commit()
    print(f"\n  Step 1 완료: {step1_total}건 치환\n")

    # ── Step 2 ─────────────────────────────────────────
    print("=" * 55)
    print("  Step 2: '기타' 레코드 키워드 재분류")
    print("=" * 55)

    others = conn.execute("""
        SELECT s.id, c.name, s.source_type, s.title, s.content
        FROM statements s JOIN candidates c ON s.candidate_id=c.id
        WHERE s.topic='기타'
    """).fetchall()

    print(f"\n  대상: {len(others)}건\n")

    reclassified = {}  # topic → count
    kept_other = 0

    for row in others:
        new_topic = guess_topic_from_text(row["title"] or "", row["content"] or "")

        if new_topic is None:
            # 분류 불가 — 기타 유지
            kept_other += 1
            continue

        conn.execute(
            "UPDATE statements SET topic=? WHERE id=?", (new_topic, row["id"])
        )
        reclassified[new_topic] = reclassified.get(new_topic, 0) + 1

    conn.commit()

    reclassified_total = sum(reclassified.values())
    print("  재분류 결과:")
    for topic, cnt in sorted(reclassified.items(), key=lambda x: -x[1]):
        print(f"    [{topic:12}] +{cnt}건")
    print(f"\n  재분류 완료: {reclassified_total}건 → 새 topic 부여")
    print(f"  기타 유지:   {kept_other}건 (비정책 콘텐츠 등)")

    # ── 최종 현황 ──────────────────────────────────────
    print("\n" + "=" * 55)
    print("  최종 Topic 분포")
    print("=" * 55)

    rows = conn.execute("""
        SELECT c.name, s.topic, COUNT(*) as cnt
        FROM statements s JOIN candidates c ON s.candidate_id=c.id
        GROUP BY c.name, s.topic
        ORDER BY c.name, cnt DESC
    """).fetchall()

    current_name = None
    for row in rows:
        if row["name"] != current_name:
            current_name = row["name"]
            total = conn.execute("""
                SELECT COUNT(*) FROM statements s
                JOIN candidates c ON s.candidate_id=c.id
                WHERE c.name=?
            """, (current_name,)).fetchone()[0]
            print(f"\n  {current_name} (총 {total}건)")
        print(f"    [{row['topic']:12}] {row['cnt']}건")

    conn.close()
    print()


if __name__ == "__main__":
    run()
