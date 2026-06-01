"""
크롤러 03 — YouTube 스크립트 수집 (yt-dlp 기반)
- yt-dlp: 채널 영상 목록 + 날짜 + 자막 다운로드
- youtube-transcript-api: 자막 추출 보조
- 최근 3개월 이내 영상만 대상
- Claude로 정책 발언 추출 → DB 저장
"""
import os
import re
import json
import time
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from utils.config import CANDIDATES, RAW_DATA_DIR
from utils.db import get_candidate_id, insert_statement, get_last_crawl_date, get_known_source_urls
from utils.claude_parser import extract_from_transcript

YT_DIR          = os.path.join(RAW_DATA_DIR, "youtube")
THREE_MONTHS_AGO = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

# yt-dlp 실행 경로 동적 탐색 (환경이 바뀌어도 자동으로 찾음)
YT_DLP = (
    shutil.which("yt-dlp")
    or "/Library/Frameworks/Python.framework/Versions/3.14/bin/yt-dlp"
)
if not os.path.exists(YT_DLP):
    raise RuntimeError(f"yt-dlp를 찾을 수 없습니다. 설치 확인: pip install yt-dlp (탐색 경로: {YT_DLP})")


# ─────────────────────────────────────────────────────────
# yt-dlp 영상 목록 수집
# ─────────────────────────────────────────────────────────
def get_channel_videos(channel_url: str, max_videos: int = 50) -> list[dict]:
    """
    yt-dlp로 채널 영상 목록 수집 (날짜 포함)
    Returns: [{"id", "title", "upload_date", "url"}, ...]
    """
    cmd = [
        YT_DLP,
        "--no-flat-playlist",
        f"--playlist-end", str(max_videos),
        "--skip-download",
        "--print", "%(upload_date)s|%(id)s|%(title)s",
        "--no-warnings",
        "--quiet",
        channel_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line or "|" not in line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            upload_date, vid_id, title = parts
            # 3개월 이내 필터
            if upload_date and upload_date != "NA" and upload_date < THREE_MONTHS_AGO:
                break  # 날짜순 정렬이므로 이후는 더 오래됨
            if vid_id:
                videos.append({
                    "id":          vid_id.strip(),
                    "title":       title.strip(),
                    "upload_date": upload_date.strip() if upload_date != "NA" else "",
                    "url":         f"https://www.youtube.com/watch?v={vid_id.strip()}",
                    "date":        f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}" if len(upload_date) == 8 else "",
                })
        return videos
    except subprocess.TimeoutExpired:
        print("    ⚠️  yt-dlp 타임아웃")
        return []
    except Exception as e:
        print(f"    ⚠️  영상 목록 수집 오류: {e}")
        return []


# ─────────────────────────────────────────────────────────
# 자막(VTT) 다운로드 및 파싱
# ─────────────────────────────────────────────────────────
def download_subtitle(video_id: str, out_dir: str) -> str | None:
    """
    yt-dlp로 자동생성 한국어 자막(VTT) 다운로드
    반환: 자막 텍스트 (실패 시 None)
    """
    out_template = os.path.join(out_dir, f"{video_id}")
    cmd = [
        YT_DLP,
        "--write-auto-subs",
        "--sub-lang", "ko",
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "-o", out_template,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
        vtt_path = f"{out_template}.ko.vtt"
        if os.path.exists(vtt_path):
            return parse_vtt(vtt_path)
    except Exception:
        pass

    # fallback: youtube-transcript-api
    return get_transcript_api(video_id)


def parse_vtt(vtt_path: str) -> str:
    """VTT 자막 파일 → 깨끗한 텍스트"""
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    texts = []
    for line in lines:
        line = line.strip()
        if not line or "-->" in line or line.startswith("WEBVTT") or line.isdigit():
            continue
        # HTML 태그 제거
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            texts.append(clean)

    # 연속 중복 제거
    unique = []
    for t in texts:
        if not unique or unique[-1] != t:
            unique.append(t)

    return " ".join(unique)


def get_transcript_api(video_id: str) -> str | None:
    """youtube-transcript-api fallback"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(["ko"])
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(["ko"])
        entries = transcript.fetch()
        return " ".join(e["text"] for e in entries)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# 후보별 처리
# ─────────────────────────────────────────────────────────
def process_candidate(name: str, channel_handle: str):
    candidate_id = get_candidate_id(name)
    if not candidate_id:
        print(f"    ⚠️  {name} 후보 미등록")
        return 0

    os.makedirs(YT_DIR, exist_ok=True)
    channel_url = f"https://www.youtube.com/{channel_handle}"

    # ── 증분 크롤링: DB에서 마지막 저장 날짜 확인 ──────────────
    last_date = get_last_crawl_date(name, "유튜브")
    known_urls = get_known_source_urls(name, "유튜브")
    if last_date:
        print(f"    → {name}: 마지막 크롤링 {last_date} 이후 영상만 수집")
    else:
        print(f"    → {name}: 최초 수집 (전체 3개월치)")

    print(f"    → {name} ({channel_handle}) 영상 목록 수집 중...")

    videos = get_channel_videos(channel_url, max_videos=30)

    # 이미 저장된 URL이거나, 마지막 크롤링 날짜 이전 영상은 건너뜀
    if last_date:
        cutoff = last_date.replace("-", "")  # YYYYMMDD 형식으로 변환
        new_videos = [
            v for v in videos
            if v["url"] not in known_urls
            and (not v["upload_date"] or v["upload_date"] > cutoff)
        ]
    else:
        new_videos = [v for v in videos if v["url"] not in known_urls]

    print(f"    → 전체 {len(videos)}개 중 신규 {len(new_videos)}개 처리")

    if not new_videos:
        print(f"    → {name}: 신규 영상 없음, 건너뜀")
        return 0

    # 영상 목록 캐시 (신규 목록만)
    cache_path = os.path.join(YT_DIR, f"{name}_videos.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(new_videos, f, ensure_ascii=False, indent=2)

    total_saved = 0

    for i, vid in enumerate(new_videos):
        vid_id = vid["id"]
        title  = vid["title"]
        date   = vid["date"]
        url    = vid["url"]

        print(f"    [{i+1}/{len(new_videos)}] {title[:45]}...")

        # 자막 다운로드
        transcript = download_subtitle(vid_id, YT_DIR)
        if not transcript or len(transcript) < 50:
            print(f"          ⚠️  자막 없음 또는 너무 짧음, 스킵")
            continue

        # 원본 저장
        raw_path = os.path.join(YT_DIR, f"{name}_{vid_id}.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(f"제목: {title}\nURL: {url}\n날짜: {date}\n\n{transcript}")

        # Claude 파싱 (API 키 있으면) → 없으면 전체 스크립트 저장
        policies = extract_from_transcript(transcript, name, title)

        if policies:
            for p in policies:
                if not p.get("content"):
                    continue
                stmt_id = insert_statement(
                    candidate_id = candidate_id,
                    topic        = p.get("topic", "기타"),
                    subtopic     = p.get("subtopic", ""),
                    title        = p.get("title") or title,
                    content      = p["content"],
                    summary      = p.get("summary", ""),
                    source_type  = "유튜브",
                    source_name  = f"{name}TV — {title[:50]}",
                    source_url   = url,
                    date         = date,
                )
                if stmt_id:
                    total_saved += 1
        else:
            # Claude 없음 → 스크립트 전체 저장 (3000자 제한)
            stmt_id = insert_statement(
                candidate_id = candidate_id,
                topic        = "기타",
                title        = title,
                content      = transcript[:3000],
                source_type  = "유튜브",
                source_name  = f"{name}TV — {title[:50]}",
                source_url   = url,
                date         = date,
            )
            if stmt_id:
                total_saved += 1

        time.sleep(0.5)

    print(f"    → {name}: {total_saved}건 저장 완료")
    return total_saved


def run():
    print("\n[03] YouTube 스크립트 수집")
    for name, info in CANDIDATES.items():
        handle = info.get("youtube", "")
        if not handle:
            continue
        process_candidate(name, f"@{handle}" if not handle.startswith("@") else handle)
    print("[03] 완료\n")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import init_db
    init_db()
    run()
