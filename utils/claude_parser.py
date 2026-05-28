"""
Claude API 기반 파서
- 긴 텍스트(PDF, 스크립트, 기사)에서 정책 발언 구조화 추출
- ANTHROPIC_API_KEY 없으면 자동 스킵
"""
import json
import re
from utils.config import ANTHROPIC_API_KEY, TOPICS

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _parse_json_response(text: str) -> list[dict] | dict | None:
    """LLM 응답에서 JSON 추출 (마크다운 코드블록 포함 처리)"""
    # ```json ... ``` 형태 제거
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    # JSON 배열 또는 객체 추출
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None


# ─────────────────────────────────────────────────────────
# 1. 주제 분류
# ─────────────────────────────────────────────────────────
def classify_topic(title: str, content: str) -> tuple[str, str, str]:
    """
    공약/발언 → (topic, subtopic, summary) 반환
    API 키 없으면 ("기타", "", "") 반환
    """
    if not ANTHROPIC_API_KEY:
        return "기타", "", ""

    topics_str = " | ".join(TOPICS)
    client = _get_client()
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"다음 선거 공약/발언을 분류해 주세요.\n\n"
                f"제목: {title}\n내용: {content[:400]}\n\n"
                f"카테고리: {topics_str}\n\n"
                '응답 형식(JSON만):\n'
                '{"topic":"카테고리명","subtopic":"세부주제(선택)","summary":"한 문장 요약"}'
            ),
        }],
    )
    result = _parse_json_response(resp.content[0].text)
    if isinstance(result, dict):
        return result.get("topic", "기타"), result.get("subtopic", ""), result.get("summary", "")
    return "기타", "", ""


# ─────────────────────────────────────────────────────────
# 2. YouTube 스크립트 → 정책 발언 추출
# ─────────────────────────────────────────────────────────
def extract_from_transcript(transcript: str, candidate_name: str, video_title: str = "") -> list[dict]:
    """
    Returns: [{"topic", "subtopic", "title", "content", "summary"}, ...]
    """
    if not ANTHROPIC_API_KEY:
        return []

    client = _get_client()
    chunk = transcript[:4000]  # 토큰 절약

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                f"다음은 {candidate_name} 후보의 YouTube 영상 '{video_title}' 스크립트입니다.\n"
                "정책·공약과 직접 관련된 발언만 추출해 주세요. "
                "인사말·잡담·광고·상업적 내용은 제외합니다.\n\n"
                f"스크립트:\n{chunk}\n\n"
                "JSON 배열로만 응답:\n"
                '[{"topic":"주제","subtopic":"세부주제","title":"발언 요약 제목","content":"실제 발언 내용","summary":"한 문장 요약"}]'
            ),
        }],
    )
    result = _parse_json_response(resp.content[0].text)
    return result if isinstance(result, list) else []


# ─────────────────────────────────────────────────────────
# 3. PDF / 선거공보 텍스트 → 정책 추출
# ─────────────────────────────────────────────────────────
def extract_from_pdf_text(pdf_text: str, candidate_name: str) -> list[dict]:
    """
    PDF 전문을 4000자 청크로 나눠 처리.
    Returns: [{"topic", "subtopic", "title", "content", "summary"}, ...]
    """
    if not ANTHROPIC_API_KEY:
        return []

    client = _get_client()
    results = []
    # 최대 20000자 (약 5~6청크)
    for i, chunk in enumerate([pdf_text[j:j+4000] for j in range(0, min(len(pdf_text), 20000), 4000)]):
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    f"{candidate_name} 후보 선거공보 텍스트에서 정책/공약 항목을 추출하세요.\n\n"
                    f"텍스트:\n{chunk}\n\n"
                    "JSON 배열로만 응답:\n"
                    '[{"topic":"주제(주택/부동산|교통/인프라|경제/일자리|교육|환경/기후|복지|안전|행정/거버넌스|문화/관광|청년|기타)","subtopic":"세부주제","title":"공약 제목","content":"공약 내용","summary":"한 문장 요약"}]'
                ),
            }],
        )
        result = _parse_json_response(resp.content[0].text)
        if isinstance(result, list):
            results.extend(result)

    return results


# ─────────────────────────────────────────────────────────
# 4. 뉴스 기사 → 후보 직접 인용 발언 추출
# ─────────────────────────────────────────────────────────
def extract_quotes_from_article(article_text: str, candidate_name: str) -> list[dict]:
    """
    Returns: [{"topic", "content", "context"}, ...]
    """
    if not ANTHROPIC_API_KEY:
        return []

    client = _get_client()
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": (
                f"다음 뉴스 기사에서 {candidate_name} 후보의 직접 발언(따옴표 안 말)만 추출하세요.\n\n"
                f"기사:\n{article_text[:3000]}\n\n"
                f"{candidate_name} 후보의 발언만, JSON 배열로만 응답:\n"
                '[{"topic":"관련 주제","content":"발언 내용","context":"발언 맥락"}]'
            ),
        }],
    )
    result = _parse_json_response(resp.content[0].text)
    return result if isinstance(result, list) else []
