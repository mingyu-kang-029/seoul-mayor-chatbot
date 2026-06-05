"""
크롤러 08 — 선거공보 PDF에서 공개 정보 추출
- 재산, 납세, 전과기록, 병역
"""
import subprocess
import re
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import DB_PATH

PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "선거공보")


def pdf_to_text(name):
    path = os.path.join(PDF_DIR, f"20260603_서울특별시_{name}_선거공보.pdf")
    result = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext 실패: {result.stderr}")
    return result.stdout


def extract_asset(text):
    """재산 총액 (천원) — 재산 섹션에서 숫자 3개 이상 있는 첫 행"""
    idx = text.find("재산")
    if idx < 0:
        return None, None, None
    section = text[idx:idx + 800]
    for line in section.split("\n"):
        nums = re.findall(r"[\d,]{4,}", line)
        if len(nums) >= 3:
            try:
                total  = int(nums[0].replace(",", ""))
                self_  = int(nums[1].replace(",", ""))
                spouse = int(nums[2].replace(",", ""))
                return total, self_, spouse
            except ValueError:
                continue
    return None, None, None


def extract_tax(text):
    """납세 총액 (천원) — 납세 섹션 '계' 행의 납세액"""
    # '계' 행에서 첫 번째 큰 숫자
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("계"):
            nums = re.findall(r"[\d,]{4,}", stripped)
            if nums:
                return int(nums[0].replace(",", "")), 0
    # 후보자 행 fallback
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("후보자"):
            nums = re.findall(r"[\d,]{4,}", stripped)
            if nums:
                return int(nums[0].replace(",", "")), 0
    return None, 0


def extract_criminal(text):
    """전과기록 — 후보자 전과기록"""
    idx = text.find("전과기록")
    if idx < 0:
        idx = text.find("전과 기록")
    if idx < 0:
        return "해당없음"

    section = text[idx:idx + 1200]
    lines = section.split("\n")

    # 후보자 행 인덱스 찾기
    cand_line_idx = None
    for i, line in enumerate(lines):
        if re.match(r'\s*후보자', line):
            cand_line_idx = i
            break

    if cand_line_idx is None:
        return "해당없음"

    cand_line = lines[cand_line_idx]

    # 후보자 행에 '해당없음' 명시된 경우
    if "해당없음" in cand_line or "해당 없음" in cand_line:
        return "해당없음"

    # bullet(•) 항목 수집 — 후보자 행부터 배우자 행 이전까지
    bullets = []
    in_cand = False
    for line in lines[cand_line_idx:]:
        if re.match(r'\s*배우자', line):
            break
        for b in re.findall(r'[•·●]\s*(.+)', line):
            b = b.strip()
            if b and not any(x in b for x in ["배우자", "직계", "신고거부", "고지거부"]):
                bullets.append(b)

    # 연속 행도 수집 (bullet 없이 이어지는 행)
    result_lines = []
    collect = False
    for line in lines[cand_line_idx:]:
        if re.match(r'\s*배우자', line):
            break
        # bullet 행 시작
        if re.search(r'[•·●]', line):
            collect = True
        if collect:
            clean = line.strip()
            if clean:
                result_lines.append(clean)

    if result_lines:
        combined = " ".join(result_lines)
        # 불필요한 부분 제거 (숫자 행 등)
        combined = re.sub(r'후보자\s+[\d,\s]+', '', combined)
        combined = re.sub(r'\s+', ' ', combined).strip()
        if len(combined) > 5:
            return combined

    if bullets:
        return "\n".join(bullets)

    return "해당없음"


def extract_military(text):
    """병역사항 — 후보자 본인 병역만"""
    idx = text.find("병역사항")
    if idx < 0:
        return "정보없음"
    section = text[idx:idx + 800]

    # 군종+계급+사유가 같은 행에 있는 경우
    m = re.search(
        r'(육군|해군|공군|해병대|사회복무|보충역|상근예비역)'
        r'[^\n]{0,30}'
        r'(병장|상병|일병|이병|중위|대위|소위|만기전역|복무만료|복무완료|원에 의한 전역|면제)',
        section,
    )
    if m:
        # 해당 행 전체 반환
        start = section.rfind("\n", 0, m.start()) + 1
        end = section.find("\n", m.end())
        line = section[start:end].strip()
        return re.sub(r'\s+', ' ', line)

    # 군종만 있고 사유가 다음 행에 있는 경우
    m2 = re.search(r'(육군|해군|공군|해병대)(이병|일병|상병|병장|중위|대위|소위)\s*\n?\s*\(([^)]+)\)', section)
    if m2:
        return f"{m2.group(1)} {m2.group(2)} ({m2.group(3)})"

    # 단순 면제
    if "면제" in section:
        m3 = re.search(r'(병역면제|면제)[^\n]{0,50}', section)
        if m3:
            return m3.group(0).strip()

    if "해당없음" in section or "해당 없음" in section:
        return "해당없음"

    return "정보없음"


# 병역: PDF 레이아웃이 복잡해 직접 정의
MILITARY_MANUAL = {
    "정원오": "육군병장 만기전역",
    "오세훈": "육군 중위 (원에 의한 전역)",
    "김정철": "육군이병 복무만료",
}


def extract_all(name):
    text = pdf_to_text(name)

    # 재산
    asset_total, asset_self, asset_spouse = extract_asset(text)

    # 납세 — 납세 섹션만 잘라서
    tax_idx = max(text.find("세금납부"), text.find("3세금납부"), text.find("세금 납부"))
    tax_section = text[tax_idx:tax_idx + 1500] if tax_idx >= 0 else text
    tax_paid, tax_delinquent = extract_tax(tax_section)

    # 전과
    criminal = extract_criminal(tax_section)

    # 병역 (수동 정의값 우선)
    military = MILITARY_MANUAL.get(name) or extract_military(text)

    return {
        "asset_total": asset_total,
        "asset_self": asset_self,
        "asset_spouse": asset_spouse,
        "tax_paid": tax_paid,
        "tax_delinquent": tax_delinquent,
        "criminal_record": criminal,
        "military_service": military,
        "public_info_raw": text[:5000],
    }


def run():
    print("\n[08] 선거공보 PDF 공개정보 추출")
    conn = sqlite3.connect(DB_PATH)

    for name in ["정원오", "오세훈", "김정철"]:
        print(f"  {name} 처리 중...")
        try:
            data = extract_all(name)
            conn.execute("""
                UPDATE candidates SET
                    asset_total      = :asset_total,
                    asset_self       = :asset_self,
                    asset_spouse     = :asset_spouse,
                    tax_paid         = :tax_paid,
                    tax_delinquent   = :tax_delinquent,
                    criminal_record  = :criminal_record,
                    military_service = :military_service,
                    public_info_raw  = :public_info_raw
                WHERE name = :name
            """, {**data, "name": name})
            conn.commit()
            print(f"    재산: {data['asset_total']:,}천원 / 납세: {data['tax_paid']:,}천원 / 전과: {data['criminal_record'][:30]} / 병역: {data['military_service']}")
        except Exception as e:
            print(f"    ⚠️  {name} 오류: {e}")

    conn.close()
    print("[08] 완료\n")


if __name__ == "__main__":
    run()
