"""
선거공보/5대공약 PDF → DB 일괄 삽입
- API 키 없이 정규식 파싱으로 동작
- 5대공약: 선관위 표준 구조 (공약순위 N / 목표 / 이행방법 / 이행기간 / 재원)
- 선거공보: 주요 정책 섹션 분할 저장
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db import get_candidate_id, insert_statement, init_db


# ─────────────────────────────────────────────────────────
# 주제 키워드 매핑
# ─────────────────────────────────────────────────────────
TOPIC_MAP = {
    "주택": "주택/부동산", "임대": "주택/부동산", "재건축": "주택/부동산",
    "재개발": "주택/부동산", "공급": "주택/부동산", "정비사업": "주택/부동산",
    "교통": "교통/인프라", "철도": "교통/인프라", "지하철": "교통/인프라",
    "버스": "교통/인프라", "도로": "교통/인프라", "통근": "교통/인프라",
    "GTX": "교통/인프라", "BRT": "교통/인프라",
    "복지": "복지", "돌봄": "복지", "어르신": "복지", "장애": "복지",
    "연금": "복지", "의료": "복지", "건강": "복지",
    "교육": "교육", "학교": "교육", "학습": "교육", "서울런": "교육",
    "청년": "청년", "창업": "청년",
    "경제": "경제/일자리", "일자리": "경제/일자리", "기업": "경제/일자리",
    "산업": "경제/일자리", "고용": "경제/일자리",
    "환경": "환경/기후", "기후": "환경/기후", "탄소": "환경/기후",
    "녹지": "환경/기후", "생태": "환경/기후",
    "안전": "안전", "재난": "안전",
    "문화": "문화/관광", "관광": "문화/관광", "예술": "문화/관광",
    "AI": "행정/거버넌스", "디지털": "행정/거버넌스",
    "행정": "행정/거버넌스", "규제": "행정/거버넌스",
    "1인": "주택/부동산",
}

TOPIC_OVERRIDES = {
    "AI행정혁신": "행정/거버넌스",
    "규제 혁신": "행정/거버넌스",
    "시민·관변단체": "행정/거버넌스",
    "복지의 재설계": "복지",
    "1인 가구": "주택/부동산",
    "압도적 주택공급": "주택/부동산",
    "주거이동 안전망": "주택/부동산",
    "교통 대전환": "교통/인프라",
    "약자와의 동행": "복지",
    "일자리": "경제/일자리",
    "통근도시": "교통/인프라",
    "공간 대전환": "행정/거버넌스",
    "청년창업": "경제/일자리",
    "아이돌봄": "복지",
    "시니어": "복지",
}


def guess_topic(text: str) -> str:
    for keyword, topic in TOPIC_OVERRIDES.items():
        if keyword in text:
            return topic
    for keyword, topic in TOPIC_MAP.items():
        if keyword in text:
            return topic
    return "행정/거버넌스"


# ─────────────────────────────────────────────────────────
# 5대공약 파싱 (김정철, 오세훈 — 표준 포맷)
# ─────────────────────────────────────────────────────────
def parse_5daegongak_standard(text: str) -> list[dict]:
    """
    선관위 5대공약 표준 포맷 파싱
    - 공약순위: N 제목 : XXX
    - □ 목 표 / □ 이행방법 / □ 이행기간 / □ 재원조달방안
    """
    pledges = []
    # 헤더 두 줄(선거명 + 후보자명) 기준으로 블록 분리
    blocks = re.split(r'선거명\s+서울특별시장선거[^\n]*\n후보자명[^\n]*\n', text)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 100:
            continue

        # 제목 추출
        title_match = re.search(
            r'공약순위[:\s]*\d*\s*(?:\([^)]+\))?\s*제목\s*[:\s]*(.+?)(?:\n|□)',
            block
        )
        if not title_match:
            title_match = re.search(r'공약순위[:\s]*\d+\s+(.+?)(?:\n)', block)
        title = title_match.group(1).strip() if title_match else block[:60].strip()

        # 섹션 분리
        goal_match = re.search(r'□\s*목\s*표(.*?)(?=□\s*이행방법|□\s*이행기간|$)', block, re.DOTALL)
        method_match = re.search(r'□\s*이행방법(.*?)(?=□\s*이행기간|□\s*재원|$)', block, re.DOTALL)
        period_match = re.search(r'□\s*이행기간(.*?)(?=□\s*재원|$)', block, re.DOTALL)
        fund_match = re.search(r'□\s*재원조달방안(.*?)$', block, re.DOTALL)

        goal   = goal_match.group(1).strip()   if goal_match   else ""
        method = method_match.group(1).strip() if method_match else ""
        period = period_match.group(1).strip() if period_match else ""
        fund   = fund_match.group(1).strip()   if fund_match   else ""

        # 내용 조합
        content_parts = []
        if goal:   content_parts.append(f"[목표]\n{goal}")
        if method: content_parts.append(f"[이행방법]\n{method}")
        if period: content_parts.append(f"[이행기간]\n{period}")
        if fund:   content_parts.append(f"[재원조달]\n{fund}")
        content = "\n\n".join(content_parts) if content_parts else block

        if len(content.strip()) < 30:
            continue

        pledges.append({
            "title":   title,
            "content": content[:3000],
            "topic":   guess_topic(title + " " + content[:200]),
        })

    return pledges


# ─────────────────────────────────────────────────────────
# 5대공약 파싱 (정원오 — 인코딩 문제로 숫자 누락)
# ─────────────────────────────────────────────────────────
def parse_5daegongak_jeong(text: str) -> list[dict]:
    """
    정원오 5대공약: 인코딩 이슈로 공약 번호가 누락됨.
    헤더 두 줄 기준으로 분리.
    """
    # 제목 키워드로 공약 분류 (정원오 5대공약 고정값)
    JEONG_PLEDGES = [
        ("30분 통근도시 실현으로 시민에게 쉼표를", "교통/인프라"),
        ("서울 공간 대전환", "행정/거버넌스"),
        ("청년창업수도 서울", "경제/일자리"),
        ("시간 공백 없는 아이돌봄", "복지"),
        ("시니어라이프캠퍼스로 서울시민 활력회복", "복지"),
    ]

    pledges = []
    blocks = re.split(r'선거명\s+서울특별시장선거[^\n]*\n후보자명[^\n]*\n', text)

    for i, block in enumerate(blocks):
        block = block.strip()
        if not block or len(block) < 80:
            continue

        # 제목 추출 (공약순위 다음 줄)
        title_match = re.search(r'공약순위\s+제목\s+(.+?)(?:\n|목\s*표)', block)
        if title_match:
            title = title_match.group(1).strip()
        elif i < len(JEONG_PLEDGES):
            # 키워드로 매핑
            for keyword, _ in JEONG_PLEDGES:
                if keyword[:10] in block:
                    title = keyword
                    break
            else:
                title = block[:60].strip()
        else:
            title = block[:60].strip()

        # 섹션 분리 (정원오는 □ 없이 "목 표", "이행방법" 등 사용)
        goal_match = re.search(r'목\s*표(.*?)(?=이행방법|이행기간|재원조달|$)', block, re.DOTALL)
        method_match = re.search(r'이행방법(.*?)(?=이행기간|재원조달|$)', block, re.DOTALL)
        period_match = re.search(r'이행기간(.*?)(?=재원조달|$)', block, re.DOTALL)
        fund_match = re.search(r'재원조달방안(.*?)$', block, re.DOTALL)

        goal   = goal_match.group(1).strip()   if goal_match   else ""
        method = method_match.group(1).strip() if method_match else ""
        period = period_match.group(1).strip() if period_match else ""
        fund   = fund_match.group(1).strip()   if fund_match   else ""

        content_parts = []
        if goal:   content_parts.append(f"[목표]\n{goal}")
        if method: content_parts.append(f"[이행방법]\n{method}")
        if period: content_parts.append(f"[이행기간]\n{period}")
        if fund:   content_parts.append(f"[재원조달]\n{fund}")
        content = "\n\n".join(content_parts) if content_parts else block

        if len(content.strip()) < 30:
            continue

        # 주제 결정
        topic = guess_topic(title + " " + content[:200])
        if i < len(JEONG_PLEDGES):
            for keyword, t in JEONG_PLEDGES:
                if keyword[:8] in title or keyword[:8] in content[:200]:
                    topic = t
                    break

        pledges.append({
            "title":   title,
            "content": content[:3000],
            "topic":   topic,
        })

    return pledges


# ─────────────────────────────────────────────────────────
# 선거공보 파싱 — 오세훈
# ─────────────────────────────────────────────────────────
def parse_gongbo_oh(text: str) -> list[dict]:
    sections = []

    # 1. 인적사항/소명서
    intro_match = re.search(r'4\.\s*소명서(.*?)(?=회색 도시|역\s*시|\Z)', text, re.DOTALL)
    if intro_match:
        intro = intro_match.group(1).strip()
        if len(intro) > 50:
            sections.append({
                "title": "오세훈 소명서 — 시민이 행복해야 합니다",
                "content": intro[:2000],
                "topic": "행정/거버넌스",
                "subtopic": "소명서",
            })

    # 2. 5년 실적 섹션들
    perf_sections = [
        ("그레이트 한강 서울 그린웨이", "환경/기후"),
        ("서울런", "교육"),
        ("디딤돌소득·동행식당·온기창고", "복지"),
        ("손목닥터 9988", "복지"),
        ("기후동행카드·다산120", "교통/인프라"),
        ("막혔던 주택공급", "주택/부동산"),
    ]
    for keyword, topic in perf_sections:
        idx = text.find(keyword)
        if idx >= 0:
            chunk = text[idx:idx+1500].strip()
            if len(chunk) > 100:
                sections.append({
                    "title": f"오세훈 실적 — {keyword}",
                    "content": chunk,
                    "topic": topic,
                    "subtopic": "민선8기 실적",
                })

    # 3. 5대 메가비전
    mega_match = re.search(r'서울의 5대 메가 비전(.*?)(?=시작된 변화|약자와의 동행|\Z)', text, re.DOTALL)
    if mega_match:
        mega_text = mega_match.group(1).strip()
        vision_blocks = [
            ("다시, 강북전성시대", "주택/부동산"),
            ("한강·그린 르네상스", "환경/기후"),
            ("첨단·창조산업 클러스터", "경제/일자리"),
            ("신통기획 +무주택자 주거 안전망", "주택/부동산"),
            ("광역 교통망 완성", "교통/인프라"),
        ]
        for keyword, topic in vision_blocks:
            idx = mega_text.find(keyword)
            if idx >= 0:
                chunk = mega_text[idx:idx+600].strip()
                if len(chunk) > 80:
                    sections.append({
                        "title": f"오세훈 비전 — {keyword}",
                        "content": chunk,
                        "topic": topic,
                        "subtopic": "5대 메가비전",
                    })

    # 4. 공약 요약 (시작된 변화 이후)
    summary_match = re.search(r'안심하고 거주하는 주거환경(.*?)(?=오세훈\s*역|역\s*시|\Z)', text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()
        if len(summary) > 100:
            sections.append({
                "title": "오세훈 공약 총괄 — 주택·교통·복지",
                "content": summary[:3000],
                "topic": "종합",
                "subtopic": "공약 요약",
            })

    # 5. 약자와의 동행 + 경제
    welfare_match = re.search(r'약자와의 동행 시즌(.*?)(?=삶의질|역\s*시|\Z)', text, re.DOTALL)
    if welfare_match:
        welfare = welfare_match.group(1).strip()
        if len(welfare) > 100:
            sections.append({
                "title": "오세훈 공약 — 약자와의 동행 시즌2 + 경제",
                "content": welfare[:3000],
                "topic": "복지",
                "subtopic": "약자동행/경제",
            })

    return sections


# ─────────────────────────────────────────────────────────
# 선거공보 파싱 — 정원오
# ─────────────────────────────────────────────────────────
def parse_gongbo_jeong(text: str) -> list[dict]:
    sections = []

    # 1. 소명서
    intro_match = re.search(r'4\.\s*소명서(.*?)(?=시민의 불편과 싸우는|\Z)', text, re.DOTALL)
    if intro_match:
        intro = intro_match.group(1).strip()
        if len(intro) > 50:
            sections.append({
                "title": "정원오 소명서 — 시민의 불편과 싸우는 일 잘하는 서울시장",
                "content": intro[:2000],
                "topic": "행정/거버넌스",
                "subtopic": "소명서",
            })

    # 2. 성동구청장 실적
    perf_match = re.search(r'압도적 성과로 증명했습니다(.*?)(?=착착투자|아시아 수도|\Z)', text, re.DOTALL)
    if perf_match:
        perf = perf_match.group(1).strip()
        if len(perf) > 50:
            sections.append({
                "title": "정원오 실적 — 성동구청장 압도적 성과",
                "content": perf[:2000],
                "topic": "행정/거버넌스",
                "subtopic": "성동구 실적",
            })

    # 3. 착착 시리즈 공약
    chakchak_sections = [
        ("착착투자", "착착창업", "경제/일자리"),
        ("착착창업", "착착관광", "경제/일자리"),
        ("착착관광", "착착개발", "문화/관광"),
        ("착착개발", "착착교통", "주택/부동산"),
        ("착착교통", "시민 모두가", "교통/인프라"),
    ]
    for start, end, topic in chakchak_sections:
        idx_s = text.find(start)
        idx_e = text.find(end)
        if idx_s >= 0:
            end_idx = idx_e if idx_e > idx_s else idx_s + 2000
            chunk = text[idx_s:end_idx].strip()
            if len(chunk) > 80:
                sections.append({
                    "title": f"정원오 공약 — {start}",
                    "content": chunk[:2000],
                    "topic": topic,
                    "subtopic": "착착 시리즈",
                })

    # 4. 착착 안전/복지/에너지/노동/소상공인 묶음
    misc_match = re.search(r"'착착 안전'(.*?)(?=세금이 아깝지|정원오가 확실히|\Z)", text, re.DOTALL)
    if misc_match:
        misc = misc_match.group(1).strip()
        if len(misc) > 80:
            sections.append({
                "title": "정원오 공약 — 착착 안전·복지·에너지·노동·소상공인",
                "content": misc[:3000],
                "topic": "복지",
                "subtopic": "기타 착착 공약",
            })

    # 5. 시민 문자 민원 → 정책 사례들
    citizen_match = re.search(r'시민의 문자 한 통(.*?)(?=서울의 모든 구|\Z)', text, re.DOTALL)
    if citizen_match:
        citizen = citizen_match.group(1).strip()
        if len(citizen) > 50:
            sections.append({
                "title": "정원오 공약 — 시민 문자 한 통이 정책으로",
                "content": citizen[:2000],
                "topic": "교통/인프라",
                "subtopic": "시민참여 정책",
            })

    return sections


# ─────────────────────────────────────────────────────────
# 선거공보 파싱 — 김정철 (이미지 PDF, 텍스트 매우 적음)
# ─────────────────────────────────────────────────────────
def parse_gongbo_kim(text: str) -> list[dict]:
    if len(text.strip()) < 50:
        return []
    # 인적사항 부분만 저장
    info_match = re.search(r'1\.인적사항(.*?)(?=2\.\s*재산|\Z)', text, re.DOTALL)
    content = info_match.group(1).strip() if info_match else text.strip()
    if len(content) < 30:
        content = text.strip()
    return [{
        "title": "김정철 선거공보 — 후보자 기본 정보",
        "content": content[:2000],
        "topic": "행정/거버넌스",
        "subtopic": "후보자 정보",
    }]


# ─────────────────────────────────────────────────────────
# 메인 삽입 함수
# ─────────────────────────────────────────────────────────
def load_raw(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run():
    init_db()
    raw_dir = "data/raw/pdfs"

    configs = [
        # (후보명, doc_type, raw_file, parser_func, source_url)
        ("김정철", "공약집",  f"{raw_dir}/김정철_공약집_raw.txt",  parse_5daegongak_standard, "https://policy.nec.go.kr"),
        ("김정철", "선거공보", f"{raw_dir}/김정철_선거공보_raw.txt", parse_gongbo_kim,          "https://policy.nec.go.kr"),
        ("오세훈", "공약집",  f"{raw_dir}/오세훈_공약집_raw.txt",  parse_5daegongak_standard, "https://policy.nec.go.kr"),
        ("오세훈", "선거공보", f"{raw_dir}/오세훈_선거공보_raw.txt", parse_gongbo_oh,           "https://policy.nec.go.kr"),
        ("정원오", "공약집",  f"{raw_dir}/정원오_공약집_raw.txt",  parse_5daegongak_jeong,    "https://policy.nec.go.kr"),
        ("정원오", "선거공보", f"{raw_dir}/정원오_선거공보_raw.txt", parse_gongbo_jeong,        "https://policy.nec.go.kr"),
    ]

    total = 0
    for name, doc_type, raw_path, parser, url in configs:
        cid = get_candidate_id(name)
        if not cid:
            print(f"  ⚠️  {name} 후보 미등록 — DB 초기화 후 01_nec_api.py 먼저 실행")
            continue

        text = load_raw(raw_path)
        items = parser(text)
        print(f"\n  [{name} / {doc_type}] → {len(items)}개 항목 파싱")

        count = 0
        for item in items:
            stmt_id = insert_statement(
                candidate_id = cid,
                topic        = item.get("topic", "기타"),
                subtopic     = item.get("subtopic", ""),
                title        = item.get("title", ""),
                content      = item["content"],
                summary      = item.get("summary", ""),
                source_type  = "선거공보" if doc_type == "선거공보" else "공약집",
                source_name  = f"선관위 {doc_type} — {name}",
                source_url   = url,
                date         = "2026-06-03",
            )
            if stmt_id:
                count += 1
                print(f"    ✅ [{item.get('topic','기타')}] {item.get('title','')[:50]}")
            else:
                print(f"    ⏩ 중복 스킵: {item.get('title','')[:50]}")

        print(f"  → {name} {doc_type}: {count}건 저장")
        total += count

    print(f"\n🎉 총 {total}건 DB 저장 완료")


if __name__ == "__main__":
    run()
