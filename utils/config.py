import os

# .env 파일 자동 로드 (python-dotenv 있으면 사용, 없으면 무시)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)
except ImportError:
    pass

# ───────────────────────────────────────────
# API Keys
# ───────────────────────────────────────────
NEC_API_KEY = "f7329732b88f8119740480873b9c5937402d39691e5fcab08a1d00649e0b705b"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ───────────────────────────────────────────
# 선거 정보
# ───────────────────────────────────────────
ELECTION_ID       = "20260603"   # 2026 지방선거
ELECTION_TYPE_CODE = "3"          # 시·도지사선거

# ───────────────────────────────────────────
# 후보자 정보
# ───────────────────────────────────────────
CANDIDATES = {
    "정원오": {
        "huboid":       "100157144",
        "party":        "더불어민주당",
        "number":       1,
        "youtube":      "@정원오tv",
        "party_site":   "https://2026win.kr/sub/introduce/view.html?seq=112",
        "performance_site": "https://www.sd.go.kr",   # 성동구청
    },
    "오세훈": {
        "huboid":       "100162984",
        "party":        "국민의힘",
        "number":       2,
        "youtube":      "@ohsehoonTV",
        "party_site":   "https://victory.peoplepowerparty.kr/view_seoul.php",
        "campaign_site": "https://ohtalk.kr",
        "performance_site": "https://news.seoul.go.kr",  # 서울시청 뉴스룸
    },
    "김정철": {
        "huboid":       "100158541",
        "party":        "개혁신당",
        "number":       4,
        "youtube":      "@서울시장후보김정철",
        "party_site":   "https://reformseoul.kr/candidates",
    },
}

# ───────────────────────────────────────────
# 언론사 검색 URL
# ───────────────────────────────────────────
NEWS_SEARCH_URLS = {
    "연합뉴스": "https://www.yna.co.kr/search/index?query={query}&ctype=A",
    "YTN":     "https://www.ytn.co.kr/search/?q={query}",
    "KBS":     "https://news.kbs.co.kr/special/search/search.html?query={query}",
}

# ───────────────────────────────────────────
# 주제 카테고리
# ───────────────────────────────────────────
TOPICS = [
    "주택/부동산",
    "교통/인프라",
    "경제/일자리",
    "교육",
    "환경/기후",
    "복지",
    "안전",
    "행정/거버넌스",
    "문화/관광",
    "청년",
    "기타",
]

# ───────────────────────────────────────────
# 경로 설정
# ───────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH      = os.path.join(BASE_DIR, "db", "candidates.db")
RAW_DATA_DIR = os.path.join(BASE_DIR, "data", "raw")

# ───────────────────────────────────────────
# API Endpoints
# ───────────────────────────────────────────
NEC_PLEDGE_API    = "https://apis.data.go.kr/9760000/ElecPrmsInfoInqireService/getCnddtElecPrmsInfoInqire"
NEC_CANDIDATE_API = "https://apis.data.go.kr/9760000/PofelcddInfoInqireService/getPofelcddRegistSttusInfoInqire"
