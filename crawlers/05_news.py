"""
크롤러 05 — 언론사 발언 수집
대상: 네이버 뉴스 검색 (연합뉴스·YTN·KBS 등 다매체 포함)
방식: 후보명으로 검색 → 기사 본문에서 직접 인용 발언 추출
기준: 후보의 직접 발언(따옴표)만 수집, 기자 논평 제외
"""
import os
import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from utils.config import CANDIDATES, RAW_DATA_DIR
from utils.db import get_candidate_id, insert_statement, get_last_crawl_date, get_known_source_urls
from utils.claude_parser import extract_quotes_from_article

NEWS_DIR = os.path.join(RAW_DATA_DIR, "news")
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
CUTOFF_DATE = datetime.now() - timedelta(days=90)  # 3개월 이내

# 편향 방지를 위해 중립적 공영/통신 매체만 허용
ALLOWED_DOMAINS = {
    "yna.co.kr",      # 연합뉴스
    "ytn.co.kr",      # YTN
    "kbs.co.kr",      # KBS
    "news.sbs.co.kr",  # SBS
    "newsis.com",      # 뉴시스 (공영 통신사)
}


# ─────────────────────────────────────────────────────────
# 검색 함수
# ─────────────────────────────────────────────────────────
def search_naver_news(query: str, pages: int = 3) -> list[dict]:
    """네이버 뉴스 검색 → 기사 URL 목록 (연합뉴스·YTN·KBS 등 포함)"""
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
                # 허용된 언론사 도메인만 수집 (편향 방지)
                domain = href.split("/")[2].replace("www.", "")
                if not any(domain == d or domain.endswith("." + d) for d in ALLOWED_DOMAINS):
                    continue
                if href in seen:
                    continue
                seen.add(href)

                # 날짜: 가장 가까운 상위 요소에서 탐색
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

                articles.append({"url": href, "title": title, "date": date_str, "source": "네이버뉴스"})
        except Exception as e:
            print(f"    ⚠️  네이버 검색 오류 (page {page}): {e}")
        time.sleep(0.5)
    return articles


# ─────────────────────────────────────────────────────────
# 기사 본문 추출
# ─────────────────────────────────────────────────────────
def fetch_article_text(url: str) -> str | None:
    """기사 URL → 본문 텍스트"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "lxml")

        # 기사 본문 선택자 (언론사별 다름 — 공통 패턴으로 시도)
        for sel in [
            "div.article-body", "div#newsContent", "div.news-body",
            "div.article_body", "div#article-view-content-div",
            "article", "div.cont_article", "div.news_txt",
            "div#articeBody", "div.news-article-body",
        ]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator="\n", strip=True)

        # fallback: <p> 태그 모아서
        paragraphs = [p.get_text(strip=True) for p in soup.select("p") if len(p.get_text(strip=True)) > 30]
        return "\n".join(paragraphs) if paragraphs else None

    except Exception as e:
        return None


def extract_direct_quotes(text: str, candidate_name: str) -> list[str]:
    """
    따옴표(" " ' ') 패턴으로 직접 발언 추출 (Claude 없을 때 fallback)
    """
    patterns = [
        rf'{re.escape(candidate_name)}\s*[가-힣]{{0,5}}\s*["\"\"]([^\"\"\"]+)["\"\"]',
        rf'["\"\"]([^\"\"\"]+)["\"\"](?:\s*[가-힣]{{0,8}}\s*{re.escape(candidate_name)})',
        r'"([^"]{10,200})"',
        r'"([^"]{10,200})"',
    ]
    quotes = []
    for pat in patterns:
        found = re.findall(pat, text)
        quotes.extend(found)
    return list(set(q.strip() for q in quotes if len(q.strip()) > 10))


# ─────────────────────────────────────────────────────────
# 후보별 처리
# ─────────────────────────────────────────────────────────
def process_candidate_news(name: str):
    candidate_id = get_candidate_id(name)
    if not candidate_id:
        print(f"    ⚠️  {name} 후보 미등록")
        return 0

    os.makedirs(NEWS_DIR, exist_ok=True)

    # ── 증분 크롤링: DB에서 마지막 저장 날짜 확인 ──────────────
    last_date = get_last_crawl_date(name, "언론")
    known_urls = get_known_source_urls(name, "언론")
    if last_date:
        print(f"    → {name}: 마지막 크롤링 {last_date} 이후 기사만 수집")
    else:
        print(f"    → {name}: 최초 수집 (전체 3개월치)")

    # 검색 쿼리: 후보명 + 서울시장 + 공약
    queries = [f"{name} 서울시장 공약", f"{name} 서울시장 발언"]
    all_articles = []

    for query in queries:
        all_articles += search_naver_news(query, pages=2)

    # 중복 URL 제거 + 증분 필터 (이미 저장된 URL, 마지막 크롤링 이전 날짜 제외)
    seen_urls = set()
    unique_articles = []
    for a in all_articles:
        if a["url"] in seen_urls or a["url"] in known_urls:
            continue
        seen_urls.add(a["url"])
        # 날짜가 있고 마지막 크롤링 날짜 이전이면 건너뜀
        if last_date and a["date"]:
            try:
                art_date = a["date"].replace(".", "-").strip()[:10]
                if art_date <= last_date:
                    continue
            except Exception:
                pass  # 날짜 파싱 실패 시 일단 포함
        unique_articles.append(a)

    if not unique_articles:
        print(f"    → {name}: 신규 기사 없음, 건너뜀")
        return 0

    print(f"    → {name}: 신규 기사 {len(unique_articles)}개 수집")

    total_saved = 0
    for i, article in enumerate(unique_articles[:30]):  # 최대 30개
        url    = article["url"]
        title  = article["title"]
        source = article["source"]
        date   = article["date"]

        body = fetch_article_text(url)
        if not body or len(body) < 100:
            continue

        # 원본 저장
        raw_path = os.path.join(NEWS_DIR, f"{name}_{source}_{i:03d}.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(f"제목: {title}\nURL: {url}\n날짜: {date}\n출처: {source}\n\n{body}")

        # Claude로 발언 추출 (있으면), 없으면 regex fallback
        quotes = extract_quotes_from_article(body, name)

        if quotes:
            for q in quotes:
                if not q.get("content") or len(q["content"]) < 10:
                    continue
                stmt_id = insert_statement(
                    candidate_id = candidate_id,
                    topic        = q.get("topic", "기타"),
                    title        = title,
                    content      = q["content"],
                    summary      = q.get("context", ""),
                    source_type  = "언론",
                    source_name  = f"{source} — {title[:50]}",
                    source_url   = url,
                    date         = date,
                )
                if stmt_id:
                    total_saved += 1
        else:
            # Regex fallback
            direct_quotes = extract_direct_quotes(body, name)
            for quote in direct_quotes[:5]:  # 기사당 최대 5개
                stmt_id = insert_statement(
                    candidate_id = candidate_id,
                    topic        = "기타",
                    title        = title,
                    content      = quote,
                    source_type  = "언론",
                    source_name  = f"{source} — {title[:50]}",
                    source_url   = url,
                    date         = date,
                )
                if stmt_id:
                    total_saved += 1

        time.sleep(0.3)

    print(f"    → {name}: 발언 {total_saved}건 저장")
    return total_saved


def run():
    print("\n[05] 언론사 발언 수집 (연합뉴스/YTN/KBS)")
    for name in CANDIDATES:
        process_candidate_news(name)
    print("[05] 완료\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import init_db
    init_db()
    run()
