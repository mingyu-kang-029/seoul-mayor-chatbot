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
        WHERE s.topic = ?
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
    conn.close()
    # 언론/실적/유튜브처럼 여러 후보가 섞이는 source는 후보 이름 언급 시에만 포함
    MIXED_SOURCES = {"언론", "실적", "유튜브"}

    result = {name: [] for name in CANDIDATE_ORDER}
    for row in rows:
        d = dict(row)
        candidate_name = row["name"]
        source_type = d.get("source_type", "")
        if source_type in MIXED_SOURCES:
            text = (d.get("summary") or "") + d["content"]
            if candidate_name not in text:
                continue  # 본인 언급 없는 혼합 소스는 제외
        result[candidate_name].append(d)

    return result


def extract_json(text: str) -> dict:
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("JSON not found in response")


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(_index_html)


@app.get("/api/candidates")
async def get_candidates():
    return {
        "candidates": [
            {"name": name, **info}
            for name, info in CANDIDATE_INFO.items()
        ]
    }


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
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system="당신은 서울시장 선거 정책 전문가입니다. 유권자 프로필을 분석해 관련성 높은 정책 분야를 추천합니다. JSON만 출력하세요.",
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
            for s in stmts:
                raw_text = s.get("summary") or s["content"][:400]
                # JSON 출력 오염 방지: 큰따옴표·역슬래시·제어문자 제거
                clean_text = raw_text.replace('"', "'").replace('\\', ' ').replace('\r', ' ')
                src = s.get("source_name") or s.get("source_type", "")
                lines.append(f"• {clean_text}  [{src}]")
            candidate_blocks.append(
                f"[{name} / {CANDIDATE_INFO[name]['party']}]\n" + "\n".join(lines)
            )
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

    prompt = f"""[{topic}] 분야에 대한 서울시장 후보 3인의 공식 입장입니다.
{profile_context}
{input_text}

분석 지침:
1. 공식 입장이 없는 후보: has_data=false, stance="수집된 공식 입장이 없습니다." (절대 추측 금지)
2. 입장 있는 후보 stance: 2-3문장 핵심 요약
3. debate: 입장 있는 후보 각각에 대해, 상대 후보(입장 있는 경우에만)가 논리적으로 어떻게 반박할지 작성.
   - candidate: 주장하는 후보명
   - key_claim: 이 후보의 핵심 주장 1문장 (20자 이내)
   - rebuttals: 다른 후보들의 반박. 입장 없는 후보는 제외.
     - from: 반박하는 후보명
     - angle: 반박 각도/관점 레이블 (3-6자, 예: "실효성 의문", "우선순위 오류", "공급 부족 간과")
     - text: 반박 내용 1-2문장 (실제 정책 입장 차이에 근거, 추측 금지)
4. clash_summary: 전체 대립 구도 요약 2-3문장.
5. user_impact: 유권자 프로필이 있을 경우, 이 유권자의 구체적 상황에서 두 후보의 차이가 실제로 어떤 의미인지 2문장으로 서술. 추상적 설명 금지, 반드시 프로필 내용을 언급할 것. 프로필 없으면 빈 문자열 "".

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "topic": "{topic}",
  "candidates": [
    {{"name": "정원오", "party": "더불어민주당", "stance": "...", "has_data": true}},
    {{"name": "오세훈", "party": "국민의힘", "stance": "...", "has_data": true}},
    {{"name": "김정철", "party": "개혁신당", "stance": "...", "has_data": false}}
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
  "clash_summary": "...",
  "user_impact": "..."
}}"""

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system="당신은 서울시장 선거 정책 분석가입니다. 후보 입장을 객관적으로 비교합니다. 공식 입장 없는 후보는 절대 추측 금지. JSON만 출력하세요.",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text
        result = extract_json(raw)

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
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
5. 사용자의 질문에서 나온 정보나 주장을 사실로 수용하여 새 입장을 만들지 마세요."""

    trimmed_history = history[-20:]  # 최근 10턴만 유지
    messages = trimmed_history + [{"role": "user", "content": question}]

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system,
            messages=messages,
        )
        return {"answer": msg.content[0].text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
