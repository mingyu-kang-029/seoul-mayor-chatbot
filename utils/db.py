"""
DB 초기화 및 CRUD 유틸리티
SQLite 기반 — 프로토타입용
"""
import sqlite3
import os
from utils.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # timeout=30: 다른 프로세스가 쓰는 중이면 최대 30초 대기 (crontab 동시 실행 대비)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL 모드: 동시 읽기/쓰기 충돌 최소화 (crontab 병렬 실행 시 안전)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30초 대기 후 포기
    return conn


def init_db():
    """테이블 생성 (없으면 생성, 있으면 유지)"""
    conn = get_connection()
    conn.executescript("""
        -- ─────────────────────────────────
        -- 후보자 테이블
        -- ─────────────────────────────────
        CREATE TABLE IF NOT EXISTS candidates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,   -- 정원오 | 오세훈 | 김정철
            party       TEXT    NOT NULL,           -- 더불어민주당 | 국민의힘 | 개혁신당
            huboid      TEXT,                       -- 선관위 API 후보자 ID
            number      INTEGER,                    -- 기호 번호
            career      TEXT,                       -- 주요 경력
            education   TEXT,                       -- 최종 학력
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        -- ─────────────────────────────────
        -- 발언/공약 메인 테이블
        -- ─────────────────────────────────
        CREATE TABLE IF NOT EXISTS statements (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            topic        TEXT,     -- 주택/부동산 | 교통/인프라 | 경제/일자리 | 교육 | 환경/기후 | 복지 | 안전 | 행정/거버넌스 | 문화/관광 | 청년 | 기타
            subtopic     TEXT,     -- 세부 주제 (예: 재건축, 공공임대, GTX 등)
            title        TEXT,     -- 공약 제목 또는 발언 요약 제목
            content      TEXT NOT NULL,  -- 실제 발언/공약 전문
            summary      TEXT,     -- Claude 요약 (1~2문장)
            source_type  TEXT NOT NULL CHECK(source_type IN (
                             '공약집', '선거공보', '토론발언', '인터뷰', '유튜브', '언론', '실적', '당홈페이지'
                         )),
            source_name  TEXT,     -- 소스명 (예: "선관위 5대공약", "정원오TV - 주거정책 영상")
            source_url   TEXT,     -- 출처 URL (출처 뱃지에 사용)
            date         TEXT,     -- YYYY-MM-DD
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        -- ─────────────────────────────────
        -- 인덱스
        -- ─────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_stmt_candidate   ON statements(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_stmt_topic       ON statements(topic);
        CREATE INDEX IF NOT EXISTS idx_stmt_source_type ON statements(source_type);
        CREATE INDEX IF NOT EXISTS idx_stmt_date        ON statements(date);
    """)
    conn.commit()
    conn.close()
    print("✅ DB 초기화 완료:", DB_PATH)


def upsert_candidate(name, party, huboid=None, number=None, career=None, education=None) -> int:
    conn = get_connection()
    conn.execute("""
        INSERT INTO candidates (name, party, huboid, number, career, education)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            party     = excluded.party,
            huboid    = excluded.huboid,
            number    = excluded.number,
            career    = excluded.career,
            education = excluded.education
    """, (name, party, huboid, number, career, education))
    conn.commit()
    row = conn.execute("SELECT id FROM candidates WHERE name=?", (name,)).fetchone()
    conn.close()
    return row[0]


def get_candidate_id(name) -> int | None:
    conn = get_connection()
    row = conn.execute("SELECT id FROM candidates WHERE name=?", (name,)).fetchone()
    conn.close()
    return row[0] if row else None


def insert_statement(
    candidate_id: int,
    content:      str,
    source_type:  str,
    topic:        str  = None,
    subtopic:     str  = None,
    title:        str  = None,
    summary:      str  = None,
    source_name:  str  = None,
    source_url:   str  = None,
    date:         str  = None,
) -> int | None:
    """중복 체크 후 삽입. 이미 존재하면 None 반환. DB 잠금 시 최대 3회 재시도."""
    import time as _time

    for attempt in range(3):
        try:
            conn = get_connection()

            # 중복 방지: 같은 후보 + 출처 URL + 내용 앞 200자
            if source_url:
                exists = conn.execute("""
                    SELECT id FROM statements
                    WHERE candidate_id=? AND source_url=? AND substr(content,1,200)=substr(?,1,200)
                """, (candidate_id, source_url, content)).fetchone()
                if exists:
                    conn.close()
                    return None

            conn.execute("""
                INSERT INTO statements
                    (candidate_id, topic, subtopic, title, content, summary,
                     source_type, source_name, source_url, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (candidate_id, topic, subtopic, title, content, summary,
                  source_type, source_name, source_url, date))
            conn.commit()
            stmt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.close()
            return stmt_id

        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < 2:
                _time.sleep(2 ** attempt)  # 1초, 2초 대기 후 재시도
                continue
            raise  # 3회 실패 시 에러 전파


def get_stats() -> dict:
    """후보별 소스 타입별 수집 현황"""
    conn = get_connection()
    stats = {}
    for row in conn.execute("""
        SELECT c.name, c.party, s.source_type, COUNT(*) AS cnt
        FROM statements s
        JOIN candidates c ON s.candidate_id = c.id
        GROUP BY c.name, s.source_type
        ORDER BY c.name, s.source_type
    """):
        name = row["name"]
        if name not in stats:
            stats[name] = {"party": row["party"], "sources": {}, "total": 0}
        stats[name]["sources"][row["source_type"]] = row["cnt"]
        stats[name]["total"] += row["cnt"]
    conn.close()
    return stats


def print_stats():
    stats = get_stats()
    print("\n📊 수집 현황")
    print("=" * 50)
    for name, info in stats.items():
        print(f"\n  {name} ({info['party']}) — 총 {info['total']}건")
        for src, cnt in info["sources"].items():
            print(f"    [{src:12}] {cnt}건")
    print("=" * 50)
