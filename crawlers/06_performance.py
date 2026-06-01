"""
크롤러 06 — 현직 실적 자료
- 오세훈: 서울시 정책 실적 (네이버 뉴스 검색)
- 정원오: 성동구 구정 실적 (네이버 뉴스 검색)
- 김정철: 현직 공직 없음 → 선거공보/5대공약 PDF에서 추출한 경력·실적 DB 직접 삽입
공약 신뢰도 판단 근거로 활용
"""
import os
import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from utils.config import RAW_DATA_DIR
from utils.db import get_candidate_id, insert_statement

PERF_DIR = os.path.join(RAW_DATA_DIR, "performance")
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


# ─────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────
def search_naver_news(query: str, pages: int = 2) -> list[dict]:
    """네이버 뉴스 검색 → 기사 URL 목록"""
    articles = []
    seen = set()
    for page in range(1, pages + 1):
        start = (page - 1) * 10 + 1
        url = (
            f"https://search.naver.com/search.naver?where=news"
            f"&query={requests.utils.quote(query)}&sort=1&start={start}"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href  = a.get("href", "")
                title = a.get_text(strip=True)
                if not (href.startswith("http") and "naver" not in href and len(title) > 15):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                date_str = ""
                parent = a.parent
                for _ in range(4):
                    if parent is None:
                        break
                    for span in parent.find_all("span", string=True):
                        t = span.get_text(strip=True)
                        if any(x in t for x in ["분 전", "시간 전", "일 전", "2026", "2025"]):
                            date_str = t
                            break
                    if date_str:
                        break
                    parent = parent.parent
                articles.append({"url": href, "title": title, "date": date_str})
        except Exception as e:
            print(f"    ⚠️  검색 오류 (page {page}): {e}")
        time.sleep(0.5)
    return articles


def fetch_article_text(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "lxml")
        for sel in [
            "div.article-body", "div#newsContent", "div.news-body",
            "div.article_body", "div#article-view-content-div",
            "article", "div.cont_article", "div.news_txt",
        ]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator="\n", strip=True)
        paras = [p.get_text(strip=True) for p in soup.select("p") if len(p.get_text(strip=True)) > 30]
        return "\n".join(paras) if paras else None
    except Exception:
        return None


def save_raw(name: str, key: str, text: str):
    os.makedirs(PERF_DIR, exist_ok=True)
    with open(os.path.join(PERF_DIR, f"{name}_{key}.txt"), "w", encoding="utf-8") as f:
        f.write(text)


# ─────────────────────────────────────────────────────────
# 오세훈 — 서울시 시정 실적 (네이버 검색)
# ─────────────────────────────────────────────────────────
def crawl_seoul_performance(candidate_id: int):
    keywords = [
        "오세훈 서울시 주택 정책 실적",
        "오세훈 서울시 교통 정책 성과",
        "오세훈 약자동행 복지 실적",
        "오세훈 서울런 교육 성과",
        "오세훈 기후동행카드 성과",
    ]
    count = 0
    seen_urls: set[str] = set()

    for kw in keywords:
        articles = search_naver_news(kw, pages=1)
        for art in articles[:5]:
            url = art["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            body = fetch_article_text(url)
            if not body or len(body) < 100:
                continue

            topic = _guess_topic(kw)
            stmt_id = insert_statement(
                candidate_id = candidate_id,
                topic        = topic,
                title        = art["title"],
                content      = body[:2000],
                source_type  = "실적",
                source_name  = f"뉴스 — {art['title'][:40]}",
                source_url   = url,
                date         = art["date"] or datetime.now().strftime("%Y-%m-%d"),
            )
            if stmt_id:
                count += 1
            time.sleep(0.3)

    print(f"    → 오세훈 실적 (서울시): {count}건 저장")
    return count


# ─────────────────────────────────────────────────────────
# 정원오 — 성동구 구정 실적 (네이버 검색)
# ─────────────────────────────────────────────────────────
def crawl_sd_performance(candidate_id: int):
    keywords = [
        "정원오 성동구청장 구정 실적",
        "정원오 성동구 복지 정책 성과",
        "정원오 성동구 도시재생 성과",
        "정원오 성동구 청년 일자리",
        "성동구청 구정 혁신 성과",
    ]
    count = 0
    seen_urls: set[str] = set()

    for kw in keywords:
        articles = search_naver_news(kw, pages=1)
        for art in articles[:5]:
            url = art["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            body = fetch_article_text(url)
            if not body or len(body) < 100:
                continue

            stmt_id = insert_statement(
                candidate_id = candidate_id,
                topic        = _guess_topic(kw),
                title        = art["title"],
                content      = body[:2000],
                source_type  = "실적",
                source_name  = f"뉴스 — {art['title'][:40]}",
                source_url   = url,
                date         = art["date"] or datetime.now().strftime("%Y-%m-%d"),
            )
            if stmt_id:
                count += 1
            time.sleep(0.3)

    print(f"    → 정원오 실적 (성동구): {count}건 저장")
    return count


# ─────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────
def _guess_topic(keyword: str) -> str:
    mapping = {
        "주택": "주택/부동산", "교통": "교통/인프라", "복지": "복지",
        "약자": "복지", "서울런": "교육", "기후": "환경/기후",
        "일자리": "경제/일자리", "청년": "청년", "안전": "안전",
    }
    for k, v in mapping.items():
        if k in keyword:
            return v
    return "행정/거버넌스"


# ─────────────────────────────────────────────────────────
# 김정철 — PDF에서 추출한 경력·실적 직접 삽입
# (현직 공직 없음 → 변호사·개혁신당 최고위원 경력 기반)
# ─────────────────────────────────────────────────────────
KIM_RECORDS = [
    {
        "topic":       "행정/거버넌스",
        "subtopic":    "법조 경력",
        "title":       "김정철 경력 — 법무법인 우리 대표변호사 (법학박사)",
        "content":     (
            "김정철 후보는 고려대학교 대학원에서 법학박사 학위를 취득하였으며, "
            "현재 법무법인 우리 대표변호사로 재직 중이다. "
            "법률 전문가로서 AI 기반 인허가 자동화, 재건축 분쟁 해결 시스템 등 "
            "법·제도 혁신 공약의 실행 근거로 제시되고 있다."
        ),
        "source_name": "선관위 선거공보 — 김정철",
        "source_url":  "https://policy.nec.go.kr",
    },
    {
        "topic":       "행정/거버넌스",
        "subtopic":    "정당 활동",
        "title":       "김정철 경력 — 개혁신당 최고위원",
        "content":     (
            "김정철 후보는 현재 개혁신당 최고위원을 맡고 있다. "
            "개혁신당 서울특별시장 후보로서 AI 행정혁신, 수의계약 제로, "
            "복지 사각지대 자동발굴 등 기존 여야와 차별화된 정책을 내세우고 있다. "
            "전국 단위 선거 경험은 없으나 당내 주요 직책을 통해 정책 역량을 쌓아왔다."
        ),
        "source_name": "선관위 선거공보 — 김정철",
        "source_url":  "https://policy.nec.go.kr",
    },
    {
        "topic":       "행정/거버넌스",
        "subtopic":    "공약 실현 가능성",
        "title":       "김정철 실적 — 현직 공직 없음, 법·제도 개혁 전문성 보유",
        "content":     (
            "김정철 후보는 현재 시장·구청장 등 공직을 맡고 있지 않아 "
            "행정 집행 실적이 없다. "
            "대신 법학박사·대표변호사로서 행정 규제·계약 구조 개혁에 대한 전문성을 강점으로 제시한다. "
            "5대 공약 전반에 걸쳐 'AI 기반 자동화'와 '법적 분쟁 해결'을 핵심 수단으로 활용하며, "
            "이는 기존 공직 경험보다 법·기술 전문가 관점에서 설계된 공약임을 의미한다."
        ),
        "source_name": "선관위 5대공약 — 김정철",
        "source_url":  "https://policy.nec.go.kr",
    },
    {
        "topic":       "행정/거버넌스",
        "subtopic":    "AI 행정 비전",
        "title":       "김정철 실적 — AI 행정혁신 공약 배경: 수의계약·복지 사각지대 문제 분석",
        "content":     (
            "김정철 후보는 서울시 수의계약 구조, 복지 신청주의, 공공조달 비효율 문제를 "
            "변호사 실무를 통해 직접 경험한 것으로 알려져 있다. "
            "1호 공약 'AI행정혁신을 통한 찾아오는 서울'은 "
            "① 서울AI Administration Portal 구축(6개월 내 시범 가동) "
            "② AI 계약감시 시스템(수의계약 원칙 금지) "
            "③ 복지 사각지대 자동발굴(단전·보험료 체납 등 위기 신호 연동)로 구성된다. "
            "재원은 서울시 IT 행정 예산 재배분(연 500~800억)과 수의계약 절감분으로 조달한다는 계획이다."
        ),
        "source_name": "선관위 5대공약 — 김정철",
        "source_url":  "https://policy.nec.go.kr",
    },
]


def insert_kim_performance(candidate_id: int) -> int:
    """김정철 PDF 기반 경력·실적 레코드 직접 삽입"""
    count = 0
    for rec in KIM_RECORDS:
        stmt_id = insert_statement(
            candidate_id = candidate_id,
            topic        = rec["topic"],
            subtopic     = rec["subtopic"],
            title        = rec["title"],
            content      = rec["content"],
            source_type  = "실적",
            source_name  = rec["source_name"],
            source_url   = rec["source_url"],
            date         = "2026-06-03",
        )
        if stmt_id:
            count += 1
    print(f"    → 김정철 실적 (PDF 기반 경력): {count}건 저장")
    return count


def run():
    print("\n[06] 현직 실적 자료 수집")

    oh_id    = get_candidate_id("오세훈")
    jeong_id = get_candidate_id("정원오")
    kim_id   = get_candidate_id("김정철")

    if oh_id:
        crawl_seoul_performance(oh_id)
    if jeong_id:
        crawl_sd_performance(jeong_id)
    if kim_id:
        insert_kim_performance(kim_id)

    print("[06] 완료\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import init_db
    init_db()
    run()
