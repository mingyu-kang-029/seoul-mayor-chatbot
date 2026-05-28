"""
전체 크롤링 파이프라인 실행
사용법:
  python run_all.py           # 전체 실행
  python run_all.py --step 1  # 특정 단계만
  python run_all.py --skip 3  # 특정 단계 건너뜀
"""
import sys
import os
import argparse
import time

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db import init_db, print_stats


STEPS = {
    1: ("선관위 Open API",        "crawlers.01_nec_api"),
    2: ("선거공보 PDF",            "crawlers.02_nec_policy"),
    3: ("YouTube 스크립트",        "crawlers.03_youtube"),
    4: ("정당/후보 선거 홈페이지", "crawlers.04_party_sites"),
    5: ("언론사 발언 수집",        "crawlers.05_news"),
    6: ("현직 실적 자료",          "crawlers.06_performance"),
}


def main():
    parser = argparse.ArgumentParser(description="서울시장 후보 데이터 수집")
    parser.add_argument("--step",  type=int, help="특정 단계만 실행 (1~6)")
    parser.add_argument("--skip",  type=int, nargs="+", help="건너뜀 단계 (예: --skip 2 3)")
    parser.add_argument("--stats", action="store_true", help="수집 현황만 출력")
    args = parser.parse_args()

    # DB 초기화
    init_db()

    if args.stats:
        print_stats()
        return

    skip = set(args.skip or [])
    steps_to_run = [args.step] if args.step else list(range(1, 7))

    print("\n" + "=" * 55)
    print("  서울시장 후보 데이터 수집 파이프라인 시작")
    print("=" * 55)

    start_total = time.time()

    for step_num in steps_to_run:
        if step_num in skip:
            print(f"\n[{step_num:02d}] SKIP: {STEPS[step_num][0]}")
            continue

        label, module_path = STEPS[step_num]
        print(f"\n{'─'*55}")
        print(f"  STEP {step_num}: {label}")
        print(f"{'─'*55}")

        try:
            start = time.time()
            module = __import__(module_path, fromlist=["run"])
            module.run()
            elapsed = time.time() - start
            print(f"  ✅ 완료 ({elapsed:.1f}초)")
        except Exception as e:
            print(f"  ❌ 오류: {e}")
            import traceback
            traceback.print_exc()

    total_elapsed = time.time() - start_total
    print(f"\n{'=' * 55}")
    print(f"  전체 수집 완료 (총 {total_elapsed:.0f}초)")
    print(f"{'=' * 55}")
    print_stats()


if __name__ == "__main__":
    main()
