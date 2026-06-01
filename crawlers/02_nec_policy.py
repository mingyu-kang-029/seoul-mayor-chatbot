"""
크롤러 02 — policy.nec.go.kr 선거공보 PDF
- JS 렌더링 필요 → Playwright 사용
- 각 후보의 선거공보 PDF 다운로드 후 pdfplumber로 텍스트 추출
- 이미지 PDF: pdf2image → Claude Vision API (우선) / pytesseract 한국어 (fallback)
- Claude로 정책 항목 구조화
"""
import os
import time
import base64
import pdfplumber
from pathlib import Path
from utils.config import CANDIDATES, RAW_DATA_DIR, ANTHROPIC_API_KEY
from utils.db import get_candidate_id, insert_statement
from utils.claude_parser import extract_from_pdf_text

PDF_DIR = os.path.join(RAW_DATA_DIR, "pdfs")

# 이미지 PDF 판단 기준
IMAGE_PDF_THRESHOLD = 550   # 페이지당 평균 550자 미만 (선거공보 정상치: 660~1252자)
KOREAN_RATIO_MIN    = 0.50  # 한글 비율 50% 미만이면 이미지/깨진 텍스트로 판단


# ─────────────────────────────────────────────────────────
# OCR: 이미지 PDF → 텍스트
# ─────────────────────────────────────────────────────────
def ocr_pdf_with_claude_vision(pdf_path: str) -> str:
    """
    PDF 페이지를 이미지로 변환 후 Claude Vision API로 OCR
    - ANTHROPIC_API_KEY 필요
    - 가장 정확한 한국어 OCR
    """
    if not ANTHROPIC_API_KEY:
        return ""

    try:
        from pdf2image import convert_from_path
        import anthropic

        pages = convert_from_path(pdf_path, dpi=200)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        full_text = []

        for i, page_img in enumerate(pages):
            # PIL Image → base64
            import io
            buf = io.BytesIO()
            page_img.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "이 선거공보 이미지에서 텍스트를 정확히 추출해 주세요. "
                                "레이아웃 구조(제목, 본문, 표)를 유지하되 순수 텍스트만 출력하세요. "
                                "광고·장식 문구는 포함하지 마세요."
                            ),
                        },
                    ],
                }],
            )
            page_text = resp.content[0].text.strip()
            if page_text:
                full_text.append(f"[페이지 {i+1}]\n{page_text}")

        return "\n\n".join(full_text)

    except Exception as e:
        print(f"    ⚠️  Claude Vision OCR 실패: {e}")
        return ""


def ocr_pdf_with_tesseract(pdf_path: str) -> str:
    """
    PDF 페이지를 이미지로 변환 후 tesseract 한국어 OCR (fallback)
    - API 키 없을 때 사용
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract

        pages = convert_from_path(pdf_path, dpi=200)
        full_text = []
        for i, page_img in enumerate(pages):
            text = pytesseract.image_to_string(page_img, lang="kor+eng", config="--psm 1")
            if text.strip():
                full_text.append(f"[페이지 {i+1}]\n{text.strip()}")
        return "\n\n".join(full_text)

    except Exception as e:
        print(f"    ⚠️  Tesseract OCR 실패: {e}")
        return ""


def extract_text_from_pdf(pdf_path: str) -> tuple[str, bool]:
    """
    PDF에서 텍스트 추출. 이미지 PDF이면 OCR 수행.
    Returns: (full_text, was_ocr_used)
    """
    # 1단계: pdfplumber로 텍스트 추출 시도
    full_text = ""
    total_pages = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            for page in pdf.pages:
                t = page.extract_text() or ""
                full_text += t + "\n"
    except Exception as e:
        print(f"    ⚠️  pdfplumber 오류: {e}")

    avg_chars = len(full_text.strip()) / max(total_pages, 1)

    # 한글 비율 계산 (깨진 텍스트 감지)
    korean_chars = sum(1 for c in full_text if '가' <= c <= '힣')
    total_chars  = max(len(full_text.strip()), 1)
    korean_ratio = korean_chars / total_chars

    is_image_pdf = avg_chars < IMAGE_PDF_THRESHOLD or korean_ratio < KOREAN_RATIO_MIN

    # 2단계: 이미지/깨진 PDF 판단 → OCR
    if is_image_pdf:
        print(f"    → 이미지/깨진 PDF 감지 (평균 {avg_chars:.0f}자/페이지, 한글 비율 {korean_ratio:.1%}) — OCR 시작...")

        if ANTHROPIC_API_KEY:
            print("    → Claude Vision API로 OCR 중...")
            ocr_text = ocr_pdf_with_claude_vision(pdf_path)
        else:
            print("    → tesseract(한국어)로 OCR 중... (API 키 설정 시 품질 향상)")
            ocr_text = ocr_pdf_with_tesseract(pdf_path)

        if ocr_text:
            print(f"    → OCR 완료: {len(ocr_text)}자 추출")
            return ocr_text, True
        else:
            print("    ⚠️  OCR 실패 — pdfplumber 결과 사용")
            return full_text, False

    return full_text, False


# ─────────────────────────────────────────────────────────
# Playwright로 policy.nec.go.kr 탐색 & PDF 다운로드
# ─────────────────────────────────────────────────────────
def download_pdfs_via_playwright():
    """
    policy.nec.go.kr 접속 → 2026 지방선거 → 서울시장 후보 공보 PDF 다운로드
    반환: {후보명: pdf_path}
    """
    from playwright.sync_api import sync_playwright

    downloaded = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            print("    → policy.nec.go.kr 접속 중...")
            page.goto("https://policy.nec.go.kr", wait_until="networkidle", timeout=20000)
            time.sleep(2)

            # 선거공보 메뉴 탐색 시도
            # (사이트 구조에 따라 selector 조정 필요)
            try:
                # '선거공보' 또는 '공약보기' 클릭
                page.click("text=선거공보", timeout=5000)
                time.sleep(1)
            except Exception:
                print("    ⚠️  선거공보 메뉴 클릭 실패 — URL 직접 시도")
                page.goto(
                    "https://policy.nec.go.kr/electionInfo/prmsView.do"
                    "?electionId=20260603&stcode=0301",
                    timeout=15000
                )
                time.sleep(2)

            # 페이지 소스에서 PDF 링크 탐색
            content = page.content()
            import re
            pdf_links = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', content, re.IGNORECASE)
            print(f"    → PDF 링크 {len(pdf_links)}개 발견")

            for link in pdf_links:
                full_url = link if link.startswith("http") else "https://policy.nec.go.kr" + link
                for name in CANDIDATES:
                    if name in content:  # 링크 근처 텍스트에 후보명 있는지 확인
                        pass  # 아래 다운로드 로직에서 처리

        except Exception as e:
            print(f"    ⚠️  Playwright 탐색 중 오류: {e}")

        finally:
            browser.close()

    return downloaded


# ─────────────────────────────────────────────────────────
# PDF 직접 다운로드 (URL 패턴 알 때)
# ─────────────────────────────────────────────────────────
def download_pdf_direct(url: str, filename: str) -> str | None:
    """URL에서 PDF 직접 다운로드 → 로컬 경로 반환"""
    import requests
    os.makedirs(PDF_DIR, exist_ok=True)
    out_path = os.path.join(PDF_DIR, filename)

    if os.path.exists(out_path):
        print(f"    → 이미 존재: {filename}")
        return out_path

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()

        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_kb = os.path.getsize(out_path) / 1024
        print(f"    → 다운로드 완료: {filename} ({size_kb:.0f}KB)")
        return out_path
    except Exception as e:
        print(f"    ⚠️  다운로드 실패 ({url}): {e}")
        return None


# ─────────────────────────────────────────────────────────
# PDF 텍스트 추출 → DB 저장
# ─────────────────────────────────────────────────────────
def parse_and_store_pdf(pdf_path: str, candidate_name: str, source_url: str, doc_type: str = "선거공보"):
    """pdfplumber → (이미지 PDF이면 OCR) → Claude 파싱 → DB 저장"""
    candidate_id = get_candidate_id(candidate_name)
    if not candidate_id:
        print(f"    ⚠️  {candidate_name} 후보 미등록")
        return 0

    # PDF 텍스트 추출 (이미지 PDF이면 자동으로 OCR)
    full_text, used_ocr = extract_text_from_pdf(pdf_path)

    if not full_text.strip():
        print(f"    ⚠️  텍스트 추출 실패: {pdf_path}")
        return 0

    # 원본 텍스트 저장 (raw) — OCR 결과 포함
    raw_path = os.path.join(RAW_DATA_DIR, "pdfs", f"{candidate_name}_{doc_type}_raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    if used_ocr:
        print(f"    → OCR 결과 저장: {raw_path}")

    # Claude 파싱
    print(f"    → Claude로 파싱 중 ({len(full_text)}자)...")
    policies = extract_from_pdf_text(full_text, candidate_name)

    if not policies:
        # Claude 없이 전문 그대로 저장
        stmt_id = insert_statement(
            candidate_id = candidate_id,
            topic        = "기타",
            title        = f"{candidate_name} {doc_type}",
            content      = full_text[:5000],
            source_type  = doc_type if doc_type in ["공약집", "선거공보"] else "선거공보",
            source_name  = f"{candidate_name} — {doc_type}",
            source_url   = source_url,
            date         = "2026-06-03",
        )
        return 1 if stmt_id else 0

    count = 0
    for p in policies:
        stmt_id = insert_statement(
            candidate_id = candidate_id,
            topic        = p.get("topic", "기타"),
            subtopic     = p.get("subtopic", ""),
            title        = p.get("title", ""),
            content      = p.get("content", ""),
            summary      = p.get("summary", ""),
            source_type  = "선거공보",
            source_name  = f"{candidate_name} — {doc_type}",
            source_url   = source_url,
            date         = "2026-06-03",
        )
        if stmt_id:
            count += 1

    print(f"    → {candidate_name} {doc_type}: {count}건 저장")
    return count


# ─────────────────────────────────────────────────────────
# 수동 PDF 등록 (이미 다운로드한 PDF)
# ─────────────────────────────────────────────────────────
def register_local_pdf(pdf_path: str, candidate_name: str, source_url: str, doc_type: str = "선거공보"):
    """수동으로 다운로드한 PDF를 DB에 등록"""
    if not os.path.exists(pdf_path):
        print(f"    ⚠️  파일 없음: {pdf_path}")
        return 0
    return parse_and_store_pdf(pdf_path, candidate_name, source_url, doc_type)


def run():
    print("\n[02] policy.nec.go.kr 선거공보 수집")

    # 1단계: Playwright로 자동 탐색 시도
    downloaded = download_pdfs_via_playwright()

    if not downloaded:
        print("  ⚠️  자동 다운로드 실패")
        print("  → data/raw/pdfs/ 에 PDF를 수동으로 넣고 register_local_pdf()를 호출하세요.")
        print("  → 예: register_local_pdf('data/raw/pdfs/정원오_선거공보.pdf', '정원오', 'URL')")

    # 2단계: 다운로드된 PDF 파싱
    for name, path in downloaded.items():
        parse_and_store_pdf(
            pdf_path       = path,
            candidate_name = name,
            source_url     = "https://policy.nec.go.kr",
        )

    # 3단계: 이미 있는 PDF 자동 처리
    existing_pdfs = list(Path(PDF_DIR).glob("*.pdf"))
    if existing_pdfs:
        print(f"\n  발견된 로컬 PDF {len(existing_pdfs)}개 처리 중...")
        for pdf_file in existing_pdfs:
            # 파일명에서 후보명 추출 (예: 정원오_선거공보.pdf)
            filename = pdf_file.stem
            for name in CANDIDATES:
                if name in filename:
                    doc_type = "선거공보" if "공보" in filename else ("공약집" if "공약" in filename else "선거공보")
                    parse_and_store_pdf(
                        pdf_path       = str(pdf_file),
                        candidate_name = name,
                        source_url     = "https://policy.nec.go.kr",
                        doc_type       = doc_type,
                    )
                    break

    print("[02] 완료\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import init_db
    init_db()
    run()
