from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import sqlite3
import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import DB_PATH, ANTHROPIC_API_KEY
import anthropic

app = FastAPI(title="서울시장 후보 정책 비교")

_web_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_web_dir, "static")), name="static")
_index_html = os.path.join(_web_dir, "templates", "index.html")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# topic별 compare 결과 캐시 — 파일로 영속화
_CACHE_FILE = os.path.join(_web_dir, "compare_cache.json")
_compare_cache: dict = {}


def _load_cache():
    global _compare_cache
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _compare_cache = json.load(f)
        except Exception:
            _compare_cache = {}


def _save_cache():
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_compare_cache, f, ensure_ascii=False)
    except Exception:
        pass


def _get_topic_latest_created_at(topic: str):
    """DB에서 해당 topic(fallback 포함)의 가장 최신 created_at 반환."""
    conn = get_db()
    row = conn.execute("""
        SELECT MAX(s.created_at) as latest
        FROM statements s
        JOIN candidates c ON s.candidate_id = c.id
        WHERE s.topic_normalized = ?
           OR s.content LIKE ?
           OR s.summary LIKE ?
    """, (topic, f"%{topic}%", f"%{topic}%")).fetchone()
    conn.close()
    return row["latest"] if row else None


def _is_cache_valid(topic: str) -> bool:
    """캐시가 존재하고 DB 최신 데이터보다 오래되지 않았으면 True."""
    entry = _compare_cache.get(topic)
    if not entry or "_cached_at" not in entry:
        return False
    db_latest = _get_topic_latest_created_at(topic)
    if db_latest is None:
        return True
    return entry["_cached_at"] >= db_latest


_load_cache()

TOPICS = [
    "주택/부동산", "교통/인프라", "경제/일자리", "교육",
    "환경/기후", "복지", "안전", "행정/거버넌스",
    "문화/관광", "청년",
]

CANDIDATE_ORDER = ["정원오", "오세훈", "김정철"]

CANDIDATE_INFO = {
    "정원오": {
        "party": "더불어민주당",
        "number": 1,
        "photo": "/static/images/jeongwoono.webp",
        "career_short": "전 성동구청장 3선",
        "career_full": "(전) 민선 6·7·8기 성동구청장",
        "education": "한양대 도시대학원 박사 수료",
    },
    "오세훈": {
        "party": "국민의힘",
        "number": 2,
        "photo": "/static/images/ohsehoon.jpg",
        "career_short": "현 서울특별시장",
        "career_full": "(현) 제39대 서울특별시장",
        "education": "고려대 대학원 법학박사",
    },
    "김정철": {
        "party": "개혁신당",
        "number": 4,
        "photo": "/static/images/kimjeongcheol.jpg",
        "career_short": "법무법인 우리 대표변호사",
        "career_full": "(현) 개혁신당 최고위원 · 법무법인 우리 대표",
        "education": "고려대 대학원 법학박사",
    },
}

CONCERN_TOPIC_HINT = """
[걱정 항목과 정책 분야 연관도 참고]
- 집값·전월세 → 주택/부동산 (매우 높음)
- 일자리·소득 → 경제/일자리 (매우 높음)
- 자녀 교육   → 교육 (매우 높음)
- 교통 불편   → 교통/인프라 (매우 높음)
- 노후·복지   → 복지 (매우 높음)
- 환경·안전   → 환경/기후, 안전 (매우 높음)
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


SOURCE_PRIORITY = {
    "공약집": 1,
    "선거공보": 2,
    "당홈페이지": 3,
    "토론발언": 4,
    "언론": 5,
    "실적": 6,
    "유튜브": 7,
}


def get_statements_for_topic(topic: str) -> dict:
    conn = get_db()
    rows = conn.execute("""
        SELECT s.title, s.content, s.summary, s.source_type,
               s.source_name, s.source_url, s.date, c.name
        FROM statements s
        JOIN candidates c ON s.candidate_id = c.id
        WHERE s.topic_normalized = ?
        ORDER BY c.number,
                 CASE s.source_type
                     WHEN '공약집'   THEN 1
                     WHEN '선거공보' THEN 2
                     WHEN '당홈페이지' THEN 3
                     WHEN '토론발언' THEN 4
                     WHEN '언론'     THEN 5
                     WHEN '실적'     THEN 6
                     WHEN '유튜브'   THEN 7
                     ELSE 8
                 END,
                 s.date DESC
    """, (topic,)).fetchall()

    MIXED_SOURCES = {"언론", "실적"}

    result = {name: [] for name in CANDIDATE_ORDER}
    for row in rows:
        d = dict(row)
        candidate_name = row["name"]
        source_type = d.get("source_type", "")
        if source_type in MIXED_SOURCES:
            text = (d.get("summary") or "") + d["content"]
            if candidate_name not in text:
                continue
        result[candidate_name].append(d)

    # 1차 조회 결과가 없는 후보에 대해 키워드 fallback 조회
    for name in CANDIDATE_ORDER:
        if result[name]:
            continue
        fallback_rows = conn.execute("""
            SELECT s.title, s.content, s.summary, s.source_type,
                   s.source_name, s.source_url, s.date, c.name
            FROM statements s
            JOIN candidates c ON s.candidate_id = c.id
            WHERE c.name = ?
              AND s.topic_normalized != '기타'
              AND (s.content LIKE ? OR s.summary LIKE ?)
            ORDER BY
                 CASE s.source_type
                     WHEN '공약집'   THEN 1
                     WHEN '선거공보' THEN 2
                     WHEN '당홈페이지' THEN 3
                     WHEN '토론발언' THEN 4
                     WHEN '언론'     THEN 5
                     WHEN '실적'     THEN 6
                     WHEN '유튜브'   THEN 7
                     ELSE 8
                 END,
                 s.date DESC
            LIMIT 10
        """, (name, f"%{topic}%", f"%{topic}%")).fetchall()

        seen_titles = set()
        for row in fallback_rows:
            d = dict(row)
            title_key = (d.get("title") or "")[:50]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            d["_fallback"] = True
            result[name].append(d)
            if len(result[name]) >= 5:
                break

    conn.close()
    return result


def extract_json(text: str) -> dict:
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    raw = match.group(1) if match else None
    if raw is None:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            raise ValueError("JSON not found in response")
        raw = match.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # JSON 문자열 내 리터럴 개행문자를 이스케이프 후 재시도
        cleaned = re.sub(r'(?<!\\)\n', ' ', raw)
        return json.loads(cleaned)


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(_index_html)


@app.get("/api/candidates")
async def get_candidates():
    conn = get_db()
    rows = conn.execute(
        "SELECT name, education, career, asset_total, asset_self, asset_spouse, "
        "tax_paid, tax_delinquent, criminal_record, military_service FROM candidates"
    ).fetchall()
    conn.close()
    db_map = {r["name"]: dict(r) for r in rows}

    result = []
    for name, info in CANDIDATE_INFO.items():
        entry = {"name": name, **info}
        db = db_map.get(name, {})
        entry["education_full"]   = db.get("education") or info.get("education", "")
        entry["career_db"]        = db.get("career") or info.get("career_full", "")
        entry["asset_total"]      = db.get("asset_total")
        entry["asset_self"]       = db.get("asset_self")
        entry["asset_spouse"]     = db.get("asset_spouse")
        entry["tax_paid"]         = db.get("tax_paid")
        entry["tax_delinquent"]   = db.get("tax_delinquent") or 0
        entry["criminal_record"]  = db.get("criminal_record") or "정보없음"
        entry["military_service"] = db.get("military_service") or "정보없음"
        result.append(entry)

    return {"candidates": result}


@app.get("/api/data-info")
async def get_data_info():
    conn = get_db()
    row = conn.execute(
        "SELECT MAX(date) as latest FROM statements WHERE date GLOB '????-??-??'"
    ).fetchone()
    conn.close()
    latest = row["latest"] if row else None
    return {"latest_date": latest}


@app.post("/api/recommend")
async def recommend(request: Request):
    profile = await request.json()

    topics_list = "\n".join(f"- {t}" for t in TOPICS)

    label_map = {
        "concern": "가장 걱정되는 것",
        "age": "연령대",
        "housing": "주거 형태",
        "employment": "고용 형태",
        "children": "자녀 상황",
        "commute": "주요 이동 수단",
        "values": "관심 분야",
    }
    profile_lines = []
    for key, label in label_map.items():
        val = profile.get(key)
        if val:
            if isinstance(val, list):
                if val:
                    profile_lines.append(f"- {label}: {', '.join(val)}")
            else:
                profile_lines.append(f"- {label}: {val}")

    freetext = profile.get("freetext", "").strip()
    profile_text = "\n".join(profile_lines) if profile_lines else "(별도 상황 정보 없음)"

    prompt = f"""다음은 서울시장 선거 유권자 프로필입니다.

[유권자 상황]
{profile_text}
"""
    if freetext:
        prompt += f"""
[유권자가 직접 작성한 상황]
{freetext}
"""

    prompt += f"""
{CONCERN_TOPIC_HINT}

아래 10개 정책 분야 중, 이 유권자에게 가장 관련성 높은 3개를 선택하세요.
'가장 걱정되는 것'이 있다면 그것과 연관된 분야를 반드시 1순위로 포함하세요.

[분야 목록]
{topics_list}

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "topics": [
    {{"topic": "분야명", "reason": "이 유권자와 관련성 (1문장, 구체적으로)"}},
    {{"topic": "분야명", "reason": "..."}},
    {{"topic": "분야명", "reason": "..."}}
  ]
}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=[{"type": "text", "text": "당신은 서울시장 선거 정책 전문가입니다. 유권자 프로필을 분석해 관련성 높은 정책 분야를 추천합니다. JSON만 출력하세요.", "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}]
        )
        return extract_json(msg.content[0].text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compare")
async def compare(request: Request):
    body = await request.json()
    topic = body.get("topic", "").strip()
    profile = body.get("profile", {})
    if not topic:
        raise HTTPException(status_code=400, detail="topic required")

    statements = get_statements_for_topic(topic)

    candidate_blocks = []
    has_any_data = False
    for name in CANDIDATE_ORDER:
        stmts = statements[name][:10]
        if stmts:
            has_any_data = True
            lines = []
            has_fallback = any(s.get("_fallback") for s in stmts)
            for s in stmts:
                raw_text = s.get("summary") or s["content"][:400]
                clean_text = raw_text.replace('"', "'").replace('\\', ' ').replace('\r', ' ').replace('\n', ' ')
                src = s.get("source_name") or s.get("source_type", "")
                fallback_label = " [타 분야 발언 중 관련 언급]" if s.get("_fallback") else ""
                lines.append(f"• {clean_text}  [{src}]{fallback_label}")
            header = f"[{name} / {CANDIDATE_INFO[name]['party']}]"
            if has_fallback:
                header += "\n(주의: 전담 공약 없음. 타 분야 발언 중 관련 언급만 존재)"
            candidate_blocks.append(header + "\n" + "\n".join(lines))
        else:
            candidate_blocks.append(
                f"[{name} / {CANDIDATE_INFO[name]['party']}]\n(수집된 공식 입장 없음)"
            )

    if not has_any_data:
        raise HTTPException(status_code=404, detail=f"{topic} 분야 데이터 없음")

    input_text = "\n\n".join(candidate_blocks)

    label_map = {
        "concern": "주요 걱정",
        "age": "연령대",
        "housing": "주거 형태",
        "employment": "고용 형태",
        "children": "자녀 상황",
        "commute": "이동 수단",
        "values": "관심 분야",
    }
    profile_lines = []
    for key, label in label_map.items():
        val = profile.get(key)
        if val:
            if isinstance(val, list):
                if val:
                    profile_lines.append(f"- {label}: {', '.join(val)}")
            else:
                profile_lines.append(f"- {label}: {val}")
    freetext = profile.get("freetext", "").strip()
    if freetext:
        profile_lines.append(f"- 추가 상황: {freetext}")
    profile_context = ("\n[유권자 프로필]\n" + "\n".join(profile_lines) + "\n") if profile_lines else ""

    # 프로필 독립적인 분석 프롬프트 (캐시 대상)
    prompt = f"""[{topic}] 분야에 대한 서울시장 후보 3인의 공식 입장입니다.
{input_text}

분석 지침:
1. 공식 입장이 없는 후보: has_data=false, stance="수집된 공식 입장이 없습니다." (절대 추측 금지)
   단, "(주의: 전담 공약 없음. 타 분야 발언 중 관련 언급만 존재)" 표시된 후보는 has_data=true로 하되,
   stance 첫 문장을 반드시 "별도 전담 공약은 없으나,"로 시작하고 관련 언급 내용을 요약하세요.
2. 입장 있는 후보 stance: 2-3문장 핵심 요약. 핵심 숫자·정책명·구체적 수치는 **굵게** 표시.
3. 모든 후보 stance_short: 카드 이미지용 초압축 한 줄 (20자 이내). 숫자+방향만 남길 것. 입장 없으면 "공식 입장 없음".
   예) "공공임대 36만 호·청년 5만", "신통기획 2.0·바로내집", "역세권 소형·법적분쟁 해소"
4. 모든 후보 stance_tag: 이 후보의 핵심 접근 방향을 나타내는 짧은 레이블 (15자 이내). 입장 없으면 빈 문자열.
   stance_short(키워드 나열)과 달리, 방향·수단·목표를 압축한 짧은 선언문으로 작성.
   예) "공공 주도 대규모 공급", "민간 규제완화·신속착공", "법적분쟁 근본 해소 우선"
5. debate: 입장 있는 후보 각각에 대해, 상대 후보(입장 있는 경우에만)가 논리적으로 어떻게 반박할지 작성.
   - candidate: 주장하는 후보명
   - key_claim: 이 후보의 핵심 주장 1문장 (20자 이내). 핵심 키워드 1개는 **굵게** 표시.
   - rebuttals: 다른 후보들의 반박. 입장 없는 후보는 제외.
     - from: 반박하는 후보명
     - angle: 반박 각도 레이블. 반드시 아래 5가지 중 가장 적합한 하나만 선택:
         "실적 불일치" — 과거 임기에서 같은 공약을 이행하지 못한 전례가 있을 때
         "재원 불명확" — 예산·재원 조달 방법이 불분명하거나 비현실적일 때
         "구조적 한계" — 법적·제도적·물리적 제약으로 실행이 어려울 때
         "수치 과장"   — 제시한 목표 수치나 효과가 근거 없이 부풀려졌을 때
         "우선순위 오류" — 문제의 근본 원인을 빗나간 처방일 때
     - text: 반박 내용 1-2문장 (실제 정책 입장 차이에 근거, 추측 금지). 반박의 핵심 근거 1곳은 **굵게** 표시.
6. clash_summary: 전체 대립 구도 요약 2-3문장. 후보 간 핵심 차이를 드러내는 키워드 2-3개는 **굵게** 표시.
7. key_diff: 세 후보의 핵심 차이를 가장 잘 드러내는 대립 구도 한 줄 (50자 이내).
   각 후보의 접근 방식을 짧은 형용어구로 수식해서 표현할 것. 단순 키워드 나열 금지.
   예) "공공 주도 대규모 공급 vs 민간 규제완화로 신속착공 vs 법적분쟁 근본 해소"
8. common_ground: 세 후보가 방향성을 공유하거나 유사한 목표를 가진 공통 입장 (1문장). 없거나 사소하면 빈 문자열.
   예) "세 후보 모두 주택 공급 확대의 필요성에 동의하나, 방식에서 크게 갈린다."

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "topic": "{topic}",
  "key_diff": "...",
  "common_ground": "...",
  "candidates": [
    {{"name": "정원오", "party": "더불어민주당", "stance_tag": "공공 주도 대규모 공급", "stance": "...", "stance_short": "...", "has_data": true}},
    {{"name": "오세훈", "party": "국민의힘", "stance_tag": "민간 규제완화 신속착공", "stance": "...", "stance_short": "...", "has_data": true}},
    {{"name": "김정철", "party": "개혁신당", "stance_tag": "", "stance": "...", "stance_short": "공식 입장 없음", "has_data": false}}
  ],
  "debate": [
    {{
      "candidate": "정원오",
      "key_claim": "핵심 주장",
      "rebuttals": [
        {{"from": "오세훈", "angle": "반박 각도", "text": "반박 내용"}}
      ]
    }}
  ],
  "clash_summary": "..."
}}"""

    if _is_cache_valid(topic):
        result = {k: v for k, v in _compare_cache[topic].items() if not k.startswith("_")}
    else:
        try:
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                system=[{"type": "text", "text": "당신은 서울시장 선거 정책 분석가입니다. 후보 입장을 객관적으로 비교합니다. 공식 입장 없는 후보는 절대 추측 금지. JSON만 출력하세요.", "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}]
            )
            result = extract_json(msg.content[0].text)
            result["sources"] = {}
            for name in CANDIDATE_ORDER:
                result["sources"][name] = [
                    {
                        "title": s.get("title") or "",
                        "source_name": s.get("source_name") or "",
                        "source_url": s.get("source_url") or "",
                        "source_type": s.get("source_type") or "",
                        "date": s.get("date") or "",
                    }
                    for s in statements[name][:8]
                ]
            from datetime import datetime, timezone
            result["_cached_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            _compare_cache[topic] = dict(result)
            _save_cache()
            result = {k: v for k, v in result.items() if not k.startswith("_")}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # user_impact: 프로필이 있을 때만 매 요청마다 별도 생성 (캐시 제외)
    result["user_impact"] = ""
    if profile_lines:
        stances_text = "\n".join(
            f"- {c['name']}: {c['stance']}"
            for c in result.get("candidates", [])
            if c.get("has_data")
        )
        impact_prompt = f"""[{topic}] 분야 서울시장 후보 입장 요약:
{stances_text}

[유권자 프로필]
{chr(10).join(profile_lines)}

이 유권자의 구체적 상황에서 후보들의 정책 차이가 실제로 어떤 의미인지 2문장으로 서술하세요.
추상적 설명 금지, 반드시 프로필 내용(연령대·주거·직업 등)을 직접 언급할 것.
유권자에게 직접 영향을 미치는 핵심 숫자나 정책명은 **굵게** 표시하세요.
JSON: {{"user_impact": "..."}}"""
        try:
            msg2 = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=[{"type": "text", "text": "서울시장 선거 정책 분석가. JSON만 출력.", "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": impact_prompt}]
            )
            result["user_impact"] = extract_json(msg2.content[0].text).get("user_impact", "")
        except Exception:
            pass

    return result


@app.post("/api/user-impact")
async def user_impact(request: Request):
    """user_impact만 빠르게 생성 — 캐시된 비교 결과 기반."""
    body = await request.json()
    topic   = body.get("topic", "").strip()
    profile = body.get("profile", {})
    if not topic:
        raise HTTPException(status_code=400, detail="topic required")

    label_map = {"concern":"주요 걱정","age":"연령대","housing":"주거 형태",
                 "employment":"고용 형태","children":"자녀 상황","commute":"이동 수단"}
    profile_lines = []
    for key, label in label_map.items():
        val = profile.get(key)
        if val:
            profile_lines.append(f"- {label}: {val if isinstance(val, str) else ', '.join(val)}")
    freetext = profile.get("freetext", "").strip()
    if freetext:
        profile_lines.append(f"- 추가 상황: {freetext}")

    if not profile_lines:
        return {"user_impact": ""}

    # 캐시에서 stance 가져오기
    cached = _compare_cache.get(topic, {})
    candidates = cached.get("candidates", [])
    if not candidates:
        # 캐시 없으면 DB에서 직접
        statements = get_statements_for_topic(topic)
        stances_text = "\n".join(
            f"- {name}: {stmts[0].get('summary') or stmts[0]['content'][:200]}"
            for name, stmts in statements.items() if stmts
        )
    else:
        stances_text = "\n".join(
            f"- {c['name']}: {c['stance']}"
            for c in candidates if c.get("has_data")
        )

    impact_prompt = f"""[{topic}] 분야 서울시장 후보 입장 요약:
{stances_text}

[유권자 프로필]
{chr(10).join(profile_lines)}

이 유권자의 구체적 상황에서 후보들의 정책 차이가 실제로 어떤 의미인지 2문장으로 서술하세요.
추상적 설명 금지, 반드시 프로필 내용(연령대·주거·직업 등)을 직접 언급할 것.
핵심 숫자나 정책명은 **굵게** 표시하세요.
JSON: {{"user_impact": "..."}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=[{"type": "text", "text": "서울시장 선거 정책 분석가. JSON만 출력.", "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": impact_prompt}]
        )
        return {"user_impact": extract_json(msg.content[0].text).get("user_impact", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


SEOUL_GU = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구",
    "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구",
    "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구",
    "서초구", "강남구", "송파구", "강동구",
]

# source_type별 "진심 가중치" — 선거용 문서일수록 낮음
LOCAL_SOURCE_WEIGHT = {
    "실적":    5,   # 선거 전 실제 행적 → 가장 높음
    "토론발언": 4,  # 즉흥·비스크립트
    "언론":    3,
    "유튜브":  2,
    "인터뷰":  2,
    "당홈페이지": 1,
    "공약집":  1,
    "선거공보": 1,
}

@app.get("/api/local-insight")
async def local_insight(gu: str):
    """
    특정 자치구에 대한 후보별 발언 조회 + AI 요약.
    ?gu=마포구 형태로 구 이름 필수.
    """
    if gu not in SEOUL_GU:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 자치구: {gu}")

    # 구 이름 변형: "마포구" → ["마포구", "마포"] (공약집은 구 없이 쓰는 경우 많음)
    gu_short = gu.replace("구", "") if gu.endswith("구") else gu
    gu_variants = list({gu, gu_short})  # 중복 제거

    def _extract_window(text: str, keyword: str, window: int = 200) -> str:
        """키워드 전후 window자를 슬라이딩으로 추출. 여러 번 등장하면 첫 번째 사용."""
        idx = text.find(keyword)
        if idx == -1:
            return ""
        start = max(0, idx - window)
        end = min(len(text), idx + len(keyword) + window)
        snippet = text[start:end].strip()
        # 앞뒤 말줄임표 처리
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        return snippet

    # 출처 우선순위: 공식 정책 문서 → 토론(구체적 공방) → 실적·언론 → 유튜브(캠페인)
    SOURCE_PRIORITY = {
        '공약집': 1, '선거공보': 2, '토론발언': 3,
        '실적': 4, '언론': 5, '당홈페이지': 6,
        '인터뷰': 7, '유튜브': 8,
    }
    YOUTUBE_TYPES = {'유튜브'}

    conn = get_db()
    result = {}

    for name in CANDIDATE_ORDER:
        rows = conn.execute("""
            SELECT s.id, s.content, s.summary, s.source_type, s.source_name
            FROM statements s
            JOIN candidates c ON s.candidate_id = c.id
            WHERE c.name = ?
        """, (name,)).fetchall()

        # 구 변형 중 하나라도 포함된 발언 추출 + 슬라이딩 윈도우로 맥락 잘라내기
        # row ID로 중복 방지 (같은 row가 gu/gu_short 두 변형에서 중복 매칭되는 것 차단)
        matched = []
        seen_row_ids = set()
        for r in rows:
            row_id = r["id"]
            if row_id in seen_row_ids:
                continue

            content = r["content"] or ""
            summary = r["summary"] or ""
            source_type = r["source_type"] or ""

            # 언론은 summary 기준, 나머지는 content 기준
            base_text = summary if source_type == "언론" else content

            # 구 변형 중 매칭된 첫 번째 키워드로 윈도우 추출
            window_text = ""
            for kw in gu_variants:
                if kw in base_text:
                    window_text = _extract_window(base_text, kw)
                    break
            if not window_text:
                continue

            seen_row_ids.add(row_id)
            matched.append({
                "window":      window_text,
                "source_type": source_type,
                "source_name": r["source_name"] or "",
                "priority":    SOURCE_PRIORITY.get(source_type, 99),
                "is_youtube":  source_type in YOUTUBE_TYPES,
            })

        # 우선순위 높은 순 정렬, 공식 소스 최대 8개 + 유튜브 최대 4개 → AI 전달
        matched.sort(key=lambda x: x["priority"])
        official_pool = [m for m in matched if not m["is_youtube"]][:8]
        yt_pool       = [m for m in matched if m["is_youtube"]][:4]
        pool = official_pool + yt_pool

        def _run_ai_filter(items: list, label: str) -> list:
            """items를 AI로 판별, relevant=true인 것만 반환."""
            if not items:
                return []
            lines = []
            for i, s in enumerate(items):
                raw = s["window"].replace("\n", " ").replace('"', "'").strip()
                lines.append(f"{i+1}. [{s['source_type']}] {raw}")

            prompt = f"""다음은 {name} 후보의 {label} 목록입니다.
각 항목이 {gu} 주민이 공감할 만한 **구체적 정책·공약·실적·문제 지적**을 담고 있는지 판단하세요.
해당하는 경우만 1-2문장으로 요약하세요.

관련 있음(relevant=true) 조건 — 아래 중 하나 이상:
- {gu}(또는 {gu_short})의 특정 사업·공약·예산·시설 계획이 명시된 경우
- {gu} 주민이 직접 체감할 수 있는 교통·주거·복지·안전 등 구체적 변화 약속이나 실적
- {gu} 관련 정책 실패나 문제를 후보가 직접 지적하거나 해결 방안을 제시한 경우

관련 없음(relevant=false) 조건 — 아래 중 하나라도 해당:
- {gu}가 단순히 지나가는 장소(토론회장, 유세 방문지)로만 등장
- 구청장·지역 인사를 만났다는 회의·간담회 사실만 있고 정책 내용이 없는 경우
- 여러 자치구를 나열하는 중 {gu}가 포함된 것에 불과한 경우
- 서울 전체에 해당하는 일반론이고 {gu}를 특정하지 않는 경우
- 부동산 시세·거래 사례·투표율·통계 수치 등 후보의 정책 의지와 무관한 사실 정보
- 내용이 모호하거나 {gu} 주민에게 실질적 정책 정보가 없는 경우

JSON 배열로만 응답 (항목 수 = 입력 수):
[{{"relevant": true, "summary": "요약"}}, {{"relevant": false, "summary": ""}}]

목록:
{chr(10).join(lines)}"""

            try:
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1500,
                    system=[{"type": "text", "text": "선거 발언 분석가. JSON 배열만 출력.", "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": prompt}]
                )
                text = msg.content[0].text.strip()
                m = re.search(r'\[.*\]', text, re.DOTALL)
                if m:
                    ai_res = json.loads(m.group())
                else:
                    return []
            except Exception:
                return []

            out = []
            seen_summaries: list[str] = []
            for i, s in enumerate(items):
                res = ai_res[i] if i < len(ai_res) else {}
                if not res.get("relevant", False):
                    continue
                summary = (res.get("summary") or "").strip()
                if not summary:
                    continue
                # 요약 텍스트 중복 제거: 앞 30자가 기존 항목과 겹치면 건너뜀
                key = summary[:30]
                if any(key in prev or prev[:30] in summary for prev in seen_summaries):
                    continue
                seen_summaries.append(summary)
                out.append({"summary": summary, "source_type": s["source_type"]})
            return out

        official_stmts = _run_ai_filter(official_pool, "공식 발언·공약·실적")
        yt_stmts       = _run_ai_filter(yt_pool,       "유튜브 캠페인 발언")

        result[name] = {
            "statements":    official_stmts[:5],   # 공식 소스
            "yt_statements": yt_stmts[:3],          # 유튜브 별도
        }

    conn.close()
    return {"gu": gu, "candidates": result}


@app.post("/api/agent")
async def agent_chat(request: Request):
    """
    후보 AI 대변인 채팅.
    - DB는 읽기 전용: 사용자 질문은 절대 DB에 저장되지 않음
    - 대화 히스토리는 클라이언트 메모리에만 유지 (Claude API도 요청으로 학습하지 않음)
    """
    body = await request.json()
    candidate_name = body.get("candidate", "").strip()
    topic = body.get("topic", "").strip()
    question = body.get("question", "").strip()
    history = body.get("history", [])

    if not (candidate_name and topic and question):
        raise HTTPException(status_code=400, detail="candidate, topic, question required")
    if candidate_name not in CANDIDATE_INFO:
        raise HTTPException(status_code=400, detail="invalid candidate")

    # DB 읽기만 수행 — 쓰기 없음
    statements = get_statements_for_topic(topic)
    cand_stmts = statements.get(candidate_name, [])[:10]

    context_lines = "\n".join(
        f"- {s.get('summary') or s['content'][:300]}  [{s.get('source_name', '')}]"
        for s in cand_stmts
    ) or "(해당 분야 공식 입장 없음)"

    info = CANDIDATE_INFO[candidate_name]

    system = f"""당신은 {candidate_name} 서울시장 후보의 AI 대변인입니다.
정당: {info['party']} | 약력: {info['career_full']}

[{topic}] 분야 관련 후보의 실제 공식 입장:
{context_lines}

[답변 규칙 — 반드시 준수]
1. 위에 제시된 공식 입장과 정책 자료에만 근거하여 답하세요.
2. 자료에 없는 내용은 추측하지 말고 "이 부분에 대한 공식 입장을 확인하기 어렵습니다"라고 답하세요.
3. 1인칭(저는, 우리는)으로 후보를 대신해 답변하되, AI 대변인임을 숨기지 마세요.
4. 답변은 200자 이내로 간결하게 작성하세요.
5. 사용자의 질문에서 나온 정보나 주장을 사실로 수용하여 새 입장을 만들지 마세요.
6. 구체적인 수치·정책명·핵심 단어는 **굵게** 표시하세요."""

    trimmed_history = history[-20:]  # 최근 10턴만 유지
    messages = trimmed_history + [{"role": "user", "content": question}]

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )
        return {"answer": msg.content[0].text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image-summary")
async def image_summary(request: Request):
    """이미지 카드용 텍스트 요약 — 각 필드를 지정 글자 수 이내로 압축"""
    import json as _json
    body = await request.json()
    data = body.get("data", {})

    cand_list = []
    for c in (data.get("candidates") or []):
        cand_list.append({
            "name": c.get("name", ""),
            "party": c.get("party", ""),
            "stance_short": c.get("stance_short", ""),
            "stance": (c.get("stance") or "")[:300],
        })

    debate_list = []
    for item in (data.get("debate") or []):
        for r in (item.get("rebuttals") or []):
            debate_list.append({
                "from": r.get("from", ""),
                "to": item.get("candidate", ""),
                "angle": r.get("angle", ""),
                "text": (r.get("text") or "")[:200],
            })

    prompt = f"""다음 서울시장 후보 정책 비교 데이터를 소셜미디어 이미지 카드(9:16)에 넣을 수 있도록 요약해주세요.
반드시 아래 JSON 형식만 출력하고, 설명이나 마크다운 없이 순수 JSON만 반환하세요.

입력 데이터:
- user_impact: {(data.get("user_impact") or "")[:400]}
- candidates: {_json.dumps(cand_list, ensure_ascii=False)}
- debate: {_json.dumps(debate_list, ensure_ascii=False)}

요약 규칙:
1. user_impact_short: user_impact를 **두 문장, 한국어 90자 이내**로 요약. 각 후보 입장 차이를 구체적으로 담을 것 (없으면 빈 문자열)
2. candidates: 각 후보의 stance_short를 **한국어 30자 이내**로, stance_detail을 **한국어 55자 이내**로 요약
   - stance_detail은 stance의 핵심 정책 수치·목표를 포함. 숫자와 기간을 살릴 것
3. debate: 각 비판의 angle은 그대로 유지, text_short를 **한국어 55자 이내 (2문장 이내)**로 요약. 비판의 구체적 근거·수치·사례를 담을 것. 짧게 자르지 말고 읽을 수 있게 작성

출력 JSON 형식 (이 형식 그대로):
{{
  "user_impact_short": "...",
  "candidates": [
    {{"name":"...", "stance_short":"...", "stance_detail":"..."}}
  ],
  "debate": [
    {{"from":"...", "to":"...", "angle":"...", "text_short":"..."}}
  ]
}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        summary = extract_json(raw)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
