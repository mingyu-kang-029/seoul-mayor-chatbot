"""
Topic 정규화 스크립트 (Claude Batch API 사용)

실행 순서:
  1. python normalize_topics_batch.py submit   → 배치 제출 후 batch_id 저장
  2. python normalize_topics_batch.py status   → 배치 진행 상황 확인
  3. python normalize_topics_batch.py apply    → 결과를 topic_normalized 컬럼에 저장
  4. python normalize_topics_batch.py stats    → 정규화 결과 통계 출력
"""
import sys
import json
import sqlite3
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.config import DB_PATH, ANTHROPIC_API_KEY
import anthropic

BATCH_ID_FILE = "normalize_batch_id.txt"

VALID_TOPICS = [
    "주택/부동산", "교통/인프라", "경제/일자리", "교육",
    "환경/기후", "복지", "안전", "행정/거버넌스",
    "문화/관광", "청년", "기타",
]

SYSTEM_PROMPT = f"""당신은 서울시장 선거 정책 분류 전문가입니다.
후보자의 발언/공약을 읽고 아래 11개 주제 중 하나로 분류하세요.

주제 목록:
{chr(10).join(f"- {t}" for t in VALID_TOPICS)}

규칙:
- 반드시 위 목록 중 하나만 출력하세요. 다른 텍스트는 절대 출력하지 마세요.
- 정치적 공방, 선거 전략, 비정책 발언은 "기타"로 분류하세요.
- 청년 주거는 "청년"이 아닌 "주택/부동산"으로 분류하세요.
- 청년 일자리는 "청년"이 아닌 "경제/일자리"로 분류하세요.
- "청년"은 청년 정책 전반(멘탈헬스, 커뮤니티, 청년 지원 종합)에만 사용하세요."""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_submit():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, content FROM statements ORDER BY id"
    ).fetchall()
    conn.close()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    requests = []
    for row in rows:
        title = (row["title"] or "").strip()
        content = (row["content"] or "")[:600].strip()
        user_text = f"제목: {title}\n\n내용: {content}"

        requests.append({
            "custom_id": str(row["id"]),
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 30,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_text}],
            },
        })

    print(f"배치 제출 중... (총 {len(requests)}건)")
    batch = client.messages.batches.create(requests=requests)

    with open(BATCH_ID_FILE, "w") as f:
        f.write(batch.id)

    print(f"배치 ID: {batch.id}")
    print(f"상태: {batch.processing_status}")
    print(f"\n완료 후 아래 명령으로 진행하세요:")
    print(f"  python normalize_topics_batch.py status")
    print(f"  python normalize_topics_batch.py apply")


def cmd_status():
    if not os.path.exists(BATCH_ID_FILE):
        print("배치 ID 파일이 없습니다. 먼저 submit을 실행하세요.")
        return

    batch_id = open(BATCH_ID_FILE).read().strip()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    batch = client.messages.batches.retrieve(batch_id)

    print(f"배치 ID: {batch_id}")
    print(f"상태: {batch.processing_status}")
    counts = batch.request_counts
    print(f"  처리 중: {counts.processing}")
    print(f"  성공:    {counts.succeeded}")
    print(f"  오류:    {counts.errored}")
    print(f"  취소:    {counts.canceled}")
    print(f"  만료:    {counts.expired}")

    if batch.processing_status == "ended":
        print("\n완료! 아래 명령으로 DB에 적용하세요:")
        print("  python normalize_topics_batch.py apply")


def _canonical(raw_topic: str) -> str:
    """비표준 topic 값을 표준값으로 매핑, 매핑 불가 시 '기타' 반환."""
    if raw_topic in VALID_TOPICS:
        return raw_topic
    REMAP = {
        "교통": "교통/인프라", "교통 인프라": "교통/인프라", "교통인프라": "교통/인프라",
        "교통·인프라": "교통/인프라", "교통·도시개발": "교통/인프라", "교통정책": "교통/인프라",
        "주택": "주택/부동산", "주거": "주택/부동산", "부동산": "주택/부동산",
        "주거정책": "주택/부동산", "주거안전": "주택/부동산",
        "경제": "경제/일자리", "일자리": "경제/일자리", "민생경제": "경제/일자리",
        "행정": "행정/거버넌스", "시정운영": "행정/거버넌스", "도시재생": "행정/거버넌스",
        "안전행정": "행정/거버넌스", "시정 운영": "행정/거버넌스",
        "도시안전": "안전", "시민안전": "안전", "재난안전": "안전",
        "문화·관광": "문화/관광", "문화예술": "문화/관광",
        "청년주거정책": "주택/부동산", "청년 주거 지원": "주택/부동산",
        "청년정책": "청년", "청년 정책": "청년",
        "노인복지": "복지", "주민복지": "복지", "돌봄": "복지",
        "환경·생태": "환경/기후", "환경·폐기물": "환경/기후",
        "종합": "기타", "시정비전": "행정/거버넌스", "도시 비전": "행정/거버넌스",
    }
    return REMAP.get(raw_topic, "기타")


def cmd_apply():
    if not os.path.exists(BATCH_ID_FILE):
        print("배치 ID 파일이 없습니다. 먼저 submit을 실행하세요.")
        return

    batch_id = open(BATCH_ID_FILE).read().strip()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        print(f"배치가 아직 처리 중입니다. 상태: {batch.processing_status}")
        return

    conn = get_conn()

    # 배치 결과를 dict로 수집
    results_map = {}
    for result in client.messages.batches.results(batch_id):
        stmt_id = int(result.custom_id)
        if result.result.type == "succeeded":
            raw = result.result.message.content[0].text.strip()
            results_map[stmt_id] = raw if raw in VALID_TOPICS else None
        else:
            results_map[stmt_id] = None  # 오류 → fallback 처리

    # 전체 statements 기준으로 적용 (배치 누락 행도 처리)
    all_rows = conn.execute("SELECT id, topic FROM statements").fetchall()

    success = 0
    fallback_canonical = 0
    fallback_gita = 0
    missing = 0

    for row in all_rows:
        sid = row["id"]

        if sid in results_map and results_map[sid] is not None:
            topic = results_map[sid]
            success += 1
        else:
            # 배치 누락이거나 오류 → 원본 topic을 표준화해서 사용
            topic = _canonical(row["topic"] or "")
            if sid not in results_map:
                missing += 1
                print(f"  [누락] id={sid} 배치 결과 없음 → '{topic}'")
            else:
                fallback_canonical += 1 if topic != "기타" else 0
                fallback_gita += 1 if topic == "기타" else 0

        conn.execute(
            "UPDATE statements SET topic_normalized=? WHERE id=?",
            (topic, sid),
        )

    conn.commit()

    # NULL 잔존 확인
    null_count = conn.execute(
        "SELECT COUNT(*) FROM statements WHERE topic_normalized IS NULL"
    ).fetchone()[0]

    conn.close()

    print(f"\n적용 완료 (총 {len(all_rows)}건):")
    print(f"  AI 분류 성공:      {success}건")
    print(f"  오류→원본 표준화:  {fallback_canonical + fallback_gita}건")
    print(f"  배치 누락:         {missing}건")
    print(f"  topic_normalized=NULL 잔존: {null_count}건")
    if null_count > 0:
        print(f"  ※ NULL이 있으면 'python3 normalize_topics_batch.py fix-null' 로 해결하세요.")
    print(f"\n통계를 보려면:")
    print(f"  python3 normalize_topics_batch.py stats")


def cmd_fix_null():
    """topic_normalized가 NULL인 행을 원본 topic 기반으로 채움."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, topic FROM statements WHERE topic_normalized IS NULL"
    ).fetchall()
    for row in rows:
        topic = _canonical(row["topic"] or "")
        conn.execute(
            "UPDATE statements SET topic_normalized=? WHERE id=?",
            (topic, row["id"]),
        )
        print(f"  id={row['id']} topic='{row['topic']}' → '{topic}'")
    conn.commit()
    conn.close()
    print(f"\nNULL {len(rows)}건 처리 완료.")


def cmd_stats():
    conn = get_conn()

    print("\n" + "=" * 55)
    print("  topic_normalized 분포")
    print("=" * 55)

    rows = conn.execute("""
        SELECT topic_normalized, COUNT(*) as cnt
        FROM statements
        WHERE topic_normalized IS NOT NULL
        GROUP BY topic_normalized
        ORDER BY cnt DESC
    """).fetchall()

    total = sum(r["cnt"] for r in rows)
    for row in rows:
        bar = "█" * (row["cnt"] // 20)
        print(f"  {row['topic_normalized']:14}  {row['cnt']:4}건  {row['cnt']/total*100:4.1f}%  {bar}")

    print(f"\n  총계: {total}건")

    # 후보별 분포
    print("\n" + "=" * 55)
    print("  후보별 topic_normalized 분포")
    print("=" * 55)

    cands = conn.execute("SELECT id, name FROM candidates ORDER BY number").fetchall()
    for cand in cands:
        rows = conn.execute("""
            SELECT topic_normalized, COUNT(*) as cnt
            FROM statements
            WHERE candidate_id=? AND topic_normalized IS NOT NULL
            GROUP BY topic_normalized
            ORDER BY cnt DESC
        """, (cand["id"],)).fetchall()
        total = sum(r["cnt"] for r in rows)
        print(f"\n  {cand['name']} (총 {total}건)")
        for row in rows:
            print(f"    {row['topic_normalized']:14}  {row['cnt']}건")

    # 정규화 전후 비교
    print("\n" + "=" * 55)
    print("  정규화 전(topic) vs 후(topic_normalized) 비교")
    print("=" * 55)
    before = conn.execute("SELECT COUNT(DISTINCT topic) FROM statements").fetchone()[0]
    after = conn.execute(
        "SELECT COUNT(DISTINCT topic_normalized) FROM statements WHERE topic_normalized IS NOT NULL"
    ).fetchone()[0]
    print(f"  고유 topic 수:  {before}개 → {after}개")

    conn.close()


COMMANDS = {
    "submit": cmd_submit,
    "status": cmd_status,
    "apply": cmd_apply,
    "fix-null": cmd_fix_null,
    "stats": cmd_stats,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        print(f"사용법: python normalize_topics_batch.py [{'|'.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[cmd]()
