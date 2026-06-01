"""
크롤러 07 — KBS 토론 자막 파싱
- 2026-05-28 서울시장 후보 토론회 자막 TXT
- >> 마커로 발언 세그먼트 분리
- Claude API로 화자 식별 + 토픽 분류 + 요약
- statements 테이블에 source_type='토론발언' 로 저장
"""

import os
import sys
import re
import sqlite3
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import ANTHROPIC_API_KEY

import anthropic

# ── 설정 ──────────────────────────────────────────────────────────────────────
TRANSCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "[Korean (auto-generated)] [LIVE]    2026 5 28()KBS [DownSub.com].txt")
DB_PATH         = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "candidates.db")
SOURCE_NAME     = "KBS 서울시장 후보 토론회 (2026-05-28)"
SOURCE_DATE     = "2026-05-28"

# 처리 대상 후보 (권영국 제외)
TARGET_CANDIDATES = {"오세훈", "정원오", "김정철"}
# 자막에서 불리는 이름 → DB 이름 정규화
NAME_NORMALIZE = {
    "정원호": "정원오",
    "정원오": "정원오",
    "오세훈": "오세훈",
    "김정철": "김정철",
}
# 사회자 키워드 (이 화자는 statements에 저장 안 함)
MODERATOR_HINTS = ["주영진", "사회자", "진행자"]

# content 앞부분에서 제거할 사회자 패턴 (정규식)
MODERATOR_PREFIX_PATTERNS = [
    r"^자[,،]\s*이번에는.{0,30}(후보|순서).{0,20}[\.\n]",
    r"^다음은\s*기호\s*\d+번.{0,30}후보입니다[\.\n]",
    r"^.{0,20}후보\s*(순서입니다|말씀해\s*주시죠|얘기해\s*주시죠|질문해\s*주시죠)[^\n]*\n",
    r"^.{0,10}수고\s*많으셨습니다[^\n]*\n",
]

BATCH_SIZE = 20  # Claude에 한 번에 보낼 세그먼트 수


# ── 1. 자막 파싱 ──────────────────────────────────────────────────────────────

def load_transcript(path: str) -> str:
    """줄번호 제거 후 전체 텍스트 반환"""
    lines = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            # 앞의 숫자+탭 제거
            cleaned = re.sub(r"^\d+\t", "", line.rstrip())
            lines.append(cleaned)
    return "\n".join(lines)


def split_segments(text: str) -> list[str]:
    """
    >> 마커 기준으로 세그먼트 분리.
    각 세그먼트는 >> 이후 다음 >> 직전까지의 텍스트.
    """
    parts = re.split(r">>\s*", text)
    segments = []
    for part in parts:
        part = part.strip()
        if len(part) > 10:   # 너무 짧은 조각 제거
            segments.append(part)
    return segments


# ── 2. Claude로 화자·토픽·요약 분류 ─────────────────────────────────────────

SYSTEM_PROMPT = """당신은 2026년 서울시장 후보 KBS 토론회 자막을 분석하는 전문가입니다.
후보는 오세훈(국민의힘), 정원오(더불어민주당, 자막에는 '정원호'로도 표기), 김정철(개혁신당), 권영국(정의당) 4명입니다.
사회자는 SBS 주영진 앵커입니다.

각 발언 세그먼트에 대해 다음을 JSON으로 반환하세요:
{
  "speaker": "오세훈" | "정원오" | "김정철" | "권영국" | "사회자" | "불명",
  "topic": "주택/부동산" | "교통/인프라" | "경제/일자리" | "교육" | "환경/기후" | "복지" | "안전" | "행정/거버넌스" | "문화/관광" | "청년" | "기타",
  "subtopic": "세부 주제 (10자 이내, 없으면 null)",
  "title": "발언 제목 (20자 이내 요약)",
  "summary": "핵심 주장 1~2문장"
}

판단 기준:
- 이전 문맥에서 사회자가 '~후보 순서입니다' 또는 '~후보가 말씀해주시죠' 처럼 소개하면 다음 >> 발언자는 해당 후보
- 후보가 본인 이름을 밝히거나 '저는 ~' 식으로 자기소개를 하면 그 화자
- 사회자 발언은 진행 안내, 질문 배분, 후보 소개 등의 내용
- 확신할 수 없으면 "불명" 반환 (절대 추측하지 말 것)
"""

def classify_batch(client: anthropic.Anthropic, segments_with_ctx: list[dict]) -> list[dict]:
    """
    segments_with_ctx: [{"index": i, "prev": "이전세그먼트", "text": "현재세그먼트"}, ...]
    반환: [{"index": i, "speaker": ..., "topic": ..., ...}, ...]
    """
    user_content = json.dumps(segments_with_ctx, ensure_ascii=False, indent=2)
    prompt = f"""아래 발언 세그먼트 목록을 분석해 주세요.
각 세그먼트에 "prev"(이전 발언 맥락)와 "text"(현재 발언)가 있습니다.
결과는 index 순서대로 JSON 배열로만 반환하세요. 다른 텍스트 없이 JSON만.

세그먼트 목록:
{user_content}
"""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # 코드블록 제거
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        results = json.loads(raw)
        return results
    except json.JSONDecodeError:
        # 파싱 실패 시 개별 항목을 "불명"으로 처리
        return [{"index": s["index"], "speaker": "불명", "topic": "기타",
                 "subtopic": None, "title": s["text"][:20], "summary": s["text"][:100]}
                for s in segments_with_ctx]


# ── 3. 사회자 문구 제거 ────────────────────────────────────────────────────────

def clean_content(text: str) -> str:
    """content 앞부분에 사회자 진행 문구가 섞여 있으면 제거 후 반환"""
    text = text.strip()
    for pattern in MODERATOR_PREFIX_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    return text


# ── 4. DB 저장 ────────────────────────────────────────────────────────────────

def get_candidate_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM candidates WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def save_statements(conn: sqlite3.Connection, items: list[dict]):
    cur = conn.cursor()
    saved = 0
    skipped = 0
    for item in items:
        speaker = item.get("speaker", "불명")
        normalized = NAME_NORMALIZE.get(speaker, speaker)

        # 저장 제외: 사회자, 불명, 권영국, 타깃 외
        if normalized not in TARGET_CANDIDATES:
            skipped += 1
            continue

        candidate_id = get_candidate_id(conn, normalized)
        if not candidate_id:
            skipped += 1
            continue

        content = clean_content(item["text"])
        if len(content) < 20:   # 너무 짧은 발언 제외
            skipped += 1
            continue

        cur.execute("""
            INSERT INTO statements
              (candidate_id, topic, subtopic, title, content, summary,
               source_type, source_name, date)
            VALUES (?, ?, ?, ?, ?, ?, '토론발언', ?, ?)
        """, (
            candidate_id,
            item.get("topic", "기타"),
            item.get("subtopic"),
            item.get("title", content[:20]),
            content,
            item.get("summary"),
            SOURCE_NAME,
            SOURCE_DATE,
        ))
        saved += 1

    conn.commit()
    return saved, skipped


# ── 4. 메인 ──────────────────────────────────────────────────────────────────

def main():
    print("=== KBS 토론 자막 파싱 시작 ===")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    conn = sqlite3.connect(DB_PATH)

    # 이미 저장된 content 목록 로드 (재실행 시 중복 건너뛰기)
    existing_contents = set(
        row[0] for row in conn.execute(
            "SELECT content FROM statements WHERE source_name = ?", (SOURCE_NAME,)
        ).fetchall()
    )
    print(f"기존 저장된 토론발언: {len(existing_contents)}건 (재실행 시 건너뜀)")

    # 자막 로드 & 세그먼트 분리
    print(f"자막 파일 로드: {TRANSCRIPT_PATH}")
    text = load_transcript(TRANSCRIPT_PATH)
    segments = split_segments(text)
    print(f"총 세그먼트: {len(segments)}개")

    # Claude 배치 분류 (미처리 세그먼트만)
    all_results = []
    for batch_start in range(0, len(segments), BATCH_SIZE):
        batch_segs = segments[batch_start: batch_start + BATCH_SIZE]
        batch_input = []
        for i, seg in enumerate(batch_segs):
            global_i = batch_start + i
            cleaned = clean_content(seg)
            if cleaned in existing_contents:
                continue  # 이미 DB에 있으면 건너뜀
            prev = segments[global_i - 1] if global_i > 0 else ""
            batch_input.append({
                "index": global_i,
                "prev": prev[-200:],
                "text": seg,
            })

        if not batch_input:
            print(f"  배치 {batch_start}~{batch_start + len(batch_segs) - 1} 모두 기존 데이터, 건너뜀")
            continue

        print(f"  배치 {batch_start}~{batch_start + len(batch_segs) - 1} 분류 중 ({len(batch_input)}건)...", end=" ")
        try:
            results = classify_batch(client, batch_input)
            # text 필드 복원 (Claude 응답엔 없으므로)
            for r in results:
                idx = r.get("index", batch_start)
                if 0 <= idx < len(segments):
                    r["text"] = segments[idx]
            all_results.extend(results)
            print(f"완료 ({len(results)}건)")
        except Exception as e:
            print(f"오류: {e}")
            for inp in batch_input:
                all_results.append({**inp, "speaker": "불명", "topic": "기타",
                                     "subtopic": None, "title": inp["text"][:20],
                                     "summary": inp["text"][:100]})

        time.sleep(0.5)   # rate limit 방지

    # DB 저장
    print(f"\nDB 저장 중...")
    saved, skipped = save_statements(conn, all_results)

    # 결과 요약
    print(f"\n=== 완료 ===")
    print(f"저장: {saved}건 / 제외(사회자·불명·권영국): {skipped}건")

    # 후보별 저장 현황
    for name in TARGET_CANDIDATES:
        cid = get_candidate_id(conn, name)
        if cid:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM statements WHERE candidate_id=? AND source_name=?",
                (cid, SOURCE_NAME)
            ).fetchone()[0]
            print(f"  {name}: {cnt}건")

    conn.close()


if __name__ == "__main__":
    main()
