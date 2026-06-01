"""
크롤러 04 — 정당/후보 공식 선거 홈페이지 (Playwright)
- 2026win.kr        : 정원오 (더불어민주당) — seq=112 직접 접근
- ohtalk.kr/complete: 오세훈 (국민의힘) — 6대 핵심공약
- reformseoul.kr    : 김정철 (개혁신당) — 보도자료/후보소개
JS 렌더링 필요 사이트 전부 Playwright 사용
"""
import os
import time
import re
from playwright.sync_api import sync_playwright
from utils.config import RAW_DATA_DIR
from utils.db import get_candidate_id, insert_statement

PARTY_DIR = os.path.join(RAW_DATA_DIR, "party_sites")


# ─────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────
def _get_browser():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    return pw, browser


def _skip_popup(page):
    """2026win.kr 거주지 팝업 건너뛰기"""
    page.evaluate("""
        () => {
            document.querySelectorAll("button").forEach(b => {
                if (b.innerText.includes("건너뛰기")) b.click();
            });
        }
    """)
    time.sleep(0.5)


def save_raw(name: str, key: str, text: str):
    os.makedirs(PARTY_DIR, exist_ok=True)
    with open(os.path.join(PARTY_DIR, f"{name}_{key}.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def _split_policies(text: str, min_len: int = 100) -> list[str]:
    """공약 번호(①②…) 또는 빈줄 기준으로 분리"""
    # 공약 번호 패턴으로 분리
    chunks = re.split(r'\n(?=[①②③④⑤⑥⑦⑧⑨⑩󰊱󰊲󰊳󰊴󰊵󰊶]|\d+\.\s)', text)
    result = []
    for c in chunks:
        c = c.strip()
        if len(c) >= min_len:
            result.append(c)
    # 분리 안 됐으면 길이 2000씩 자르기
    if not result:
        result = [text[i:i+2000] for i in range(0, len(text), 2000) if len(text[i:i+2000].strip()) >= min_len]
    return result


# ─────────────────────────────────────────────────────────
# 정원오 — 2026win.kr (seq=112)
# ─────────────────────────────────────────────────────────
def crawl_2026win(candidate_id: int) -> int:
    pw, browser = _get_browser()
    count = 0
    try:
        page = browser.new_page()
        page.goto(
            "https://2026win.kr/sub/introduce/view.html?seq=112",
            wait_until="networkidle", timeout=25000,
        )
        time.sleep(2)
        _skip_popup(page)

        body_text = page.inner_text("body")
        save_raw("정원오", "2026win", body_text)

        # 주요 공약 섹션: "주요 공약" 이후 부분만 추출
        if "주요 공약" in body_text:
            policy_section = body_text[body_text.index("주요 공약"):]
        else:
            policy_section = body_text

        # 공약 요약 (한줄 요약) 저장
        if "한줄 공약요약" in body_text:
            idx = body_text.index("한줄 공약요약")
            summary_end = body_text.find("\n", idx + 20)
            summary = body_text[idx + len("한줄 공약요약"):summary_end].strip()
            if summary:
                insert_statement(
                    candidate_id=candidate_id,
                    topic="종합",
                    title="정원오 — 공약 한줄 요약",
                    content=summary,
                    source_type="당홈페이지",
                    source_name="더불어민주당 2026win.kr",
                    source_url="https://2026win.kr/sub/introduce/view.html?seq=112",
                    date="2026-06-03",
                )
                count += 1

        # 공약 본문 분할 저장
        chunks = _split_policies(policy_section, min_len=80)
        for chunk in chunks[:15]:
            stmt_id = insert_statement(
                candidate_id=candidate_id,
                topic=_guess_topic(chunk),
                title=f"정원오 공약 — {chunk[:40].strip()}",
                content=chunk[:2000],
                source_type="당홈페이지",
                source_name="더불어민주당 2026win.kr",
                source_url="https://2026win.kr/sub/introduce/view.html?seq=112",
                date="2026-06-03",
            )
            if stmt_id:
                count += 1

        page.close()
    except Exception as e:
        print(f"    ⚠️  2026win.kr 오류: {e}")
    finally:
        browser.close()
        pw.stop()

    print(f"    → 정원오 (2026win.kr): {count}건 저장")
    return count


# ─────────────────────────────────────────────────────────
# 오세훈 — ohtalk.kr/complete (6대 핵심공약)
# ─────────────────────────────────────────────────────────
def _split_long_chunk(chunk: str, max_len: int = 1500) -> list[str]:
    """긴 chunk를 빈줄 기준으로 추가 분리"""
    if len(chunk) <= max_len:
        return [chunk]
    sub = [c.strip() for c in re.split(r'\n{2,}', chunk) if len(c.strip()) >= 80]
    return sub if sub else [chunk[:max_len]]


def crawl_ohtalk(candidate_id: int) -> int:
    pw, browser = _get_browser()
    count = 0
    try:
        page = browser.new_page()
        # ① networkidle로 JS 렌더링 완료까지 대기
        page.goto("https://ohtalk.kr/complete", wait_until="networkidle", timeout=30000)
        # ② KEY PLEDGES 텍스트가 DOM에 나타날 때까지 명시적 대기
        try:
            page.wait_for_selector("text=KEY PLEDGES", timeout=15000)
        except Exception:
            # KEY PLEDGES가 없으면 핵심공약 텍스트로 fallback
            try:
                page.wait_for_selector("text=핵심공약", timeout=5000)
            except Exception:
                pass  # 둘 다 없으면 현재 상태로 진행

        body_text = page.inner_text("body")
        save_raw("오세훈", "ohtalk_complete", body_text)

        # KEY PLEDGES 섹션 추출
        if "KEY PLEDGES" in body_text:
            policy_section = body_text[body_text.index("KEY PLEDGES"):]
        elif "핵심공약" in body_text:
            policy_section = body_text[body_text.index("핵심공약"):]
        else:
            policy_section = body_text

        # ③ 1차 분리 후 긴 chunk는 추가 분리
        chunks = _split_policies(policy_section, min_len=80)
        all_chunks = []
        for chunk in chunks:
            all_chunks.extend(_split_long_chunk(chunk, max_len=1500))

        for chunk in all_chunks[:30]:
            stmt_id = insert_statement(
                candidate_id=candidate_id,
                topic=_guess_topic(chunk),
                title=f"오세훈 공약 — {chunk[:40].strip()}",
                content=chunk[:2000],
                source_type="당홈페이지",
                source_name="오세훈 공식 선거 홈페이지 ohtalk.kr",
                source_url="https://ohtalk.kr/complete",
                date="2026-06-03",
            )
            if stmt_id:
                count += 1

        page.close()
    except Exception as e:
        print(f"    ⚠️  ohtalk.kr 오류: {e}")
    finally:
        browser.close()
        pw.stop()

    print(f"    → 오세훈 (ohtalk.kr): {count}건 저장")
    return count


# ─────────────────────────────────────────────────────────
# 김정철 — reformseoul.kr (후보소개 + 보도자료)
# ─────────────────────────────────────────────────────────
def crawl_reformseoul(candidate_id: int) -> int:
    pw, browser = _get_browser()
    count = 0
    try:
        page = browser.new_page()

        # 1. 후보 소개 페이지
        page.goto("https://reformseoul.kr/candidates", wait_until="networkidle", timeout=20000)
        time.sleep(2)
        candidates_text = page.inner_text("body")
        save_raw("김정철", "reformseoul_candidates", candidates_text)
        if len(candidates_text) > 100:
            stmt_id = insert_statement(
                candidate_id=candidate_id,
                topic="종합",
                title="김정철 — 개혁신당 서울시장 후보 소개",
                content=candidates_text[:2000],
                source_type="당홈페이지",
                source_name="개혁신당 서울특별시당 reformseoul.kr",
                source_url="https://reformseoul.kr/candidates",
                date="2026-06-03",
            )
            if stmt_id:
                count += 1

        # 2. 보도자료 목록 → 각 기사 방문
        page.goto("https://reformseoul.kr/news/press-releases", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        links = page.eval_on_selector_all(
            'a[href*="press-releases/"]',
            'els => els.map(e => ({href: e.href, text: e.innerText.trim().substring(0,60)}))'
        )
        unique_links = {l["href"]: l for l in links if l["text"] and l["href"] != "https://reformseoul.kr/news/press-releases"}.values()

        for link_info in list(unique_links)[:10]:
            try:
                page.goto(link_info["href"], wait_until="networkidle", timeout=15000)
                time.sleep(1)
                article_text = page.inner_text("main, article, body")
                if len(article_text) > 100:
                    stmt_id = insert_statement(
                        candidate_id=candidate_id,
                        topic=_guess_topic(article_text),
                        title=link_info["text"][:80],
                        content=article_text[:2000],
                        source_type="당홈페이지",
                        source_name="개혁신당 서울시당 보도자료",
                        source_url=link_info["href"],
                        date="2026-06-03",
                    )
                    if stmt_id:
                        count += 1
            except Exception as e:
                print(f"    ⚠️  기사 오류 ({link_info['href'][:50]}): {e}")
            time.sleep(0.5)

        page.close()
    except Exception as e:
        print(f"    ⚠️  reformseoul.kr 오류: {e}")
    finally:
        browser.close()
        pw.stop()

    print(f"    → 김정철 (reformseoul.kr): {count}건 저장")
    return count


# ─────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────
def _guess_topic(text: str) -> str:
    mapping = {
        "주택": "주택/부동산", "임대": "주택/부동산", "개발": "주택/부동산",
        "교통": "교통/인프라", "지하철": "교통/인프라", "버스": "교통/인프라", "도로": "교통/인프라",
        "복지": "복지", "돌봄": "복지", "어르신": "복지", "장애": "복지",
        "교육": "교육", "학교": "교육", "청년": "청년", "일자리": "경제/일자리",
        "경제": "경제/일자리", "창업": "경제/일자리", "기업": "경제/일자리",
        "환경": "환경/기후", "기후": "환경/기후", "탄소": "환경/기후",
        "안전": "안전", "재난": "안전", "문화": "문화/관광", "관광": "문화/관광",
        "AI": "디지털/AI", "디지털": "디지털/AI",
    }
    for k, v in mapping.items():
        if k in text:
            return v
    return "행정/거버넌스"


# ─────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────
def run():
    print("\n[04] 정당/후보 선거 홈페이지 수집 (Playwright)")

    jeong_id = get_candidate_id("정원오")
    oh_id    = get_candidate_id("오세훈")
    kim_id   = get_candidate_id("김정철")

    if jeong_id:
        crawl_2026win(jeong_id)
    if oh_id:
        crawl_ohtalk(oh_id)
    if kim_id:
        crawl_reformseoul(kim_id)

    print("[04] 완료\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import init_db
    init_db()
    run()
