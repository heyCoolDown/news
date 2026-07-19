"""
뉴스 모니터 크롤러
- 보유종목 뉴스: 네이버 뉴스 API
- IT/생명공학/순수과학: RSS 피드
- 정치 뉴스 블랙리스트 필터
- 결과: news.json 저장
"""

import sys
import os
import json
import time
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

sys.stdout.reconfigure(encoding='utf-8')

# ── .env 로드 (로컬 실행용) ────────────────────────────────
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_dotenv()

# ── 번역 ───────────────────────────────────────────────────
try:
    from deep_translator import GoogleTranslator
    _translator = GoogleTranslator(source='auto', target='ko')
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False

def translate(text):
    if not TRANSLATION_AVAILABLE or not text:
        return text
    try:
        return _translator.translate(text[:4500]) or text
    except Exception:
        return text

# ── 본문 전체 추출 ──────────────────────────────────────────
try:
    import trafilatura
    from trafilatura.settings import use_config
    _trafilatura_config = use_config()
    _trafilatura_config.set("DEFAULT", "DOWNLOAD_TIMEOUT", "8")
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

def cap_text(text, limit=3000):
    """너무 긴 본문은 문단 경계에서 잘라냄"""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = cut.rfind('\n')
    if idx > limit * 0.5:
        cut = cut[:idx]
    return cut.rstrip() + '\n\n...(중략)'

def fetch_full_text(url, timeout=8):
    """기사 원문 URL에서 본문 전체 추출 (실패 시 빈 문자열 반환 → 호출부에서 summary로 폴백)"""
    if not TRAFILATURA_AVAILABLE or not url:
        return ""
    try:
        downloaded = trafilatura.fetch_url(url, config=_trafilatura_config)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return cap_text(text.strip(), 3000) if text else ""
    except Exception:
        return ""

def enrich_full_text(items, sleep=0.15):
    """각 기사에 본문 전체(content) 필드 추가, 실패 시 summary로 폴백"""
    for item in items:
        full = fetch_full_text(item.get("url", ""))
        if full:
            if item.get("lang") == "en":
                full = translate(full)
            item["content"] = full
        else:
            item["content"] = item.get("summary", "")
        time.sleep(sleep)
    return items

# ── 설정 ──────────────────────────────────────────────────
NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

HOLDINGS_API_URL      = "http://168.107.56.144:5000/api/data"
HOLDINGS_LOGIN_URL    = "http://168.107.56.144:5000/login"
HOLDINGS_PASSWORD     = os.environ.get("HOLDINGS_PASSWORD", "")

KST = timezone(timedelta(hours=9))

# 정치 블랙리스트 키워드
POLITICS_BLACKLIST = [
    "대통령", "국회", "여당", "야당", "민주당", "국민의힘", "정의당",
    "정치", "선거", "탄핵", "의원", "국무총리", "장관", "청와대",
    "대선", "총선", "지방선거", "공천", "당대표", "원내대표",
    "보수", "진보", "좌파", "우파", "집권", "야권", "여권",
]

# RSS 피드 목록 (IT/과학/생명공학)
RSS_FEEDS = [
    # 국내 IT
    {"name": "전자신문",    "url": "https://www.etnews.com/rss/allnews.xml",           "category": "IT"},
    {"name": "ZDNet Korea", "url": "https://feeds.feedburner.com/zdkorea",             "category": "IT"},
    {"name": "디지털데일리", "url": "http://www.ddaily.co.kr/rss/allArticle.xml",      "category": "IT"},
    {"name": "AI타임스",    "url": "https://www.aitimes.com/rss/allArticle.xml",       "category": "IT"},
    # 국내 과학
    {"name": "헬로디디",    "url": "https://www.hellodd.com/rss/allArticle.xml",       "category": "과학"},
    # 국내 의료
    {"name": "코메디닷컴",  "url": "https://kormedi.com/feed/",                        "category": "의료"},
    # 해외 IT/과학 (영문)
    {"name": "Hacker News",    "url": "https://hnrss.org/frontpage",                   "category": "IT",   "lang": "en"},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/",       "category": "IT",   "lang": "en"},
    {"name": "Nature News",     "url": "https://www.nature.com/nature.rss",            "category": "과학", "lang": "en"},
    {"name": "ScienceDaily",    "url": "https://www.sciencedaily.com/rss/all.xml",     "category": "과학", "lang": "en"},
    # 해외 의료 (영문)
    {"name": "Medical Xpress", "url": "https://medicalxpress.com/rss-feed/",           "category": "의료", "lang": "en"},
    {"name": "BBC Health",     "url": "https://feeds.bbci.co.uk/news/health/rss.xml",  "category": "의료", "lang": "en"},
    # 해외 기이한사건 (영문)
    {"name": "Oddity Central", "url": "https://www.odditycentral.com/feed",            "category": "기이", "lang": "en"},
    {"name": "Atlas Obscura",  "url": "https://www.atlasobscura.com/feeds/latest",     "category": "기이", "lang": "en"},
    {"name": "Mysterious Univ","url": "https://mysteriousuniverse.org/feed/",          "category": "기이", "lang": "en"},
    # 해외 흥미 (영문)
    {"name": "Interesting Eng","url": "https://interestingengineering.com/feed",       "category": "흥미", "lang": "en"},
    {"name": "Futurism",       "url": "https://futurism.com/feed",                     "category": "흥미", "lang": "en"},
]

# ── HTML 태그 제거 ─────────────────────────────────────────
class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fed = []
    def handle_data(self, d):
        self.fed.append(d)
    def get_data(self):
        return ''.join(self.fed)

def strip_tags(html):
    s = MLStripper()
    try:
        s.feed(html or "")
        return s.get_data().strip()
    except:
        return re.sub(r'<[^>]+>', '', html or '').strip()

def summarize(text, length=None):
    """HTML 태그 제거 후 공백 정리 (length 지정 시에만 잘라냄)"""
    clean = strip_tags(text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if length is None or len(clean) <= length:
        return clean
    return clean[:length].rsplit(' ', 1)[0] + '...'

# ── 정치 필터 ──────────────────────────────────────────────
def is_politics(title, desc=""):
    text = (title or "") + " " + (desc or "")
    return any(kw in text for kw in POLITICS_BLACKLIST)

# ── 보유종목 가져오기 ──────────────────────────────────────
def get_holdings():
    import http.cookiejar
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        # 로그인
        if HOLDINGS_PASSWORD:
            login_data = urllib.parse.urlencode({"password": HOLDINGS_PASSWORD}).encode("utf-8")
            login_req = urllib.request.Request(
                HOLDINGS_LOGIN_URL, data=login_data,
                headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}
            )
            with opener.open(login_req, timeout=5) as _:
                pass
        else:
            print("[보유종목] HOLDINGS_PASSWORD 미설정")

        # 세션으로 API 호출
        req = urllib.request.Request(HOLDINGS_API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
        positions = data.get("positions") or []
        holdings = []
        for p in positions:
            name = p.get("name", "").strip()
            code = p.get("code", "").strip()
            if name:
                holdings.append({"name": name, "code": code})
        print(f"[보유종목] {len(holdings)}종목: {[h['name'] for h in holdings]}")
        return holdings
    except Exception as e:
        print(f"[보유종목] 가져오기 실패: {e}")
        return []

# ── 네이버 뉴스 API ────────────────────────────────────────
def naver_news_search(query, display=5):
    """네이버 뉴스 검색 API"""
    try:
        enc_query = urllib.parse.quote(query)
        url = f"https://openapi.naver.com/v1/search/news.json?query={enc_query}&display={display}&sort=date"
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id",     NAVER_CLIENT_ID)
        req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data.get("items", [])
    except Exception as e:
        print(f"[네이버] {query} 검색 실패: {e}")
        return []

def parse_naver_date(date_str):
    """네이버 날짜 파싱 (RFC 2822 형식)"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except:
        return datetime.now(KST).strftime("%Y-%m-%d %H:%M")

# ── RSS 파싱 ───────────────────────────────────────────────
def parse_rss(feed_info, max_items=8):
    """RSS 피드 파싱 (표준 라이브러리만 사용)
    <item> 블록 단위로 파싱 — 문서 전체에서 태그를 한꺼번에 긁으면
    <image><title> 같은 채널 부가 태그 때문에 title/link 인덱스가 어긋날 수 있어
    (예: Yahoo Finance RSS) 블록 단위로 격리해서 파싱한다.
    """
    items = []
    try:
        req = urllib.request.Request(feed_info["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            raw = res.read().decode("utf-8", errors="replace")

        blocks = re.findall(r'<item>(.*?)</item>', raw, re.DOTALL)

        count = 0
        for block in blocks:
            if count >= max_items:
                break

            m_title = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', block, re.DOTALL)
            title = strip_tags(((m_title.group(1) or m_title.group(2)) if m_title else "").strip())
            if not title:
                continue

            m_desc = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>', block, re.DOTALL)
            desc = strip_tags(((m_desc.group(1) or m_desc.group(2)) if m_desc else "").strip())

            m_link = re.search(r'<link>(https?://[^<]+)</link>', block)
            link = m_link.group(1).strip() if m_link else ""

            m_date = re.search(r'<pubDate>(.*?)</pubDate>', block)
            date_raw = m_date.group(1) if m_date else ""

            # 날짜 파싱
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_raw)
                pub_date = dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            except:
                pub_date = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

            if is_politics(title, desc):
                continue

            summary = summarize(desc)
            if feed_info.get("lang") == "en":
                title   = translate(title)
                summary = translate(summary)

            items.append({
                "title":    title,
                "summary":  summary,
                "url":      link,
                "source":   feed_info["name"],
                "category": feed_info["category"],
                "date":     pub_date,
                "lang":     feed_info.get("lang", "ko"),
            })
            count += 1

    except Exception as e:
        print(f"[RSS] {feed_info['name']} 실패: {e}")

    return items

# ── 야후 파이낸스 헤드라인 ─────────────────────────────────
YAHOO_FINANCE_FEED = {
    "name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex",
    "category": "경제", "lang": "en",
}

# ── 일본어 학습 (청공문고 소설 하루 한 페이지) ──────────────
GONGITSUNE_START_DATE = datetime(2026, 7, 20, tzinfo=KST).date()  # 1페이지가 노출되는 날짜
GONGITSUNE_PATH = os.path.join(os.path.dirname(__file__), "data", "gongitsune.json")

def get_daily_reading():
    """data/gongitsune.json(청공문고 공공영역 소설, 페이지별 번역/문법/단어 수록)에서
    오늘 날짜에 해당하는 페이지를 골라 반환. 네트워크 호출 없음 — 정적 데이터 순환.
    """
    try:
        with open(GONGITSUNE_PATH, encoding="utf-8") as f:
            book = json.load(f)
    except Exception as e:
        print(f"[일본어학습] gongitsune.json 로드 실패: {e}")
        return None

    pages = book.get("pages", [])
    if not pages:
        return None

    day_index = (datetime.now(KST).date() - GONGITSUNE_START_DATE).days
    day_index = max(0, min(day_index, len(pages) - 1))
    page = pages[day_index]

    return {
        "title":       book.get("title", ""),
        "title_ko":    book.get("title_ko", ""),
        "author_ko":   book.get("author_ko", ""),
        "source":      book.get("source", ""),
        "source_url":  book.get("source_url", ""),
        "page":        page["page"],
        "total_pages": len(pages),
        "chapter":     page.get("chapter", ""),
        "jp_html":     page.get("jp_html", ""),
        "ko":          page.get("ko", ""),
        "vocab":       page.get("vocab", []),
        "grammar":     page.get("grammar", []),
        "category":    "일본어",
        "date":        datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    }

# ── 중복 제거 ──────────────────────────────────────────────
def deduplicate(news_list):
    seen = set()
    result = []
    for item in news_list:
        key = item["title"][:30]
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

# ── 메인 ──────────────────────────────────────────────────
def main():
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*50}")
    print(f"[시작] {now_kst}")
    print(f"{'='*50}")

    all_news = {
        "holdings": [],   # 보유종목 뉴스
        "tech":     [],   # IT/과학 뉴스
        "trends":   [],   # 야후 파이낸스 헤드라인
        "japanese": [],   # 일본어 학습 (청공문고 소설 하루 한 페이지)
        "updated":  now_kst,
    }

    # 1. 보유종목 뉴스
    holdings = get_holdings()
    for stock in holdings:
        print(f"[보유종목 검색] {stock['name']}")
        items = naver_news_search(stock["name"], display=3)
        for item in items:
            title = strip_tags(item.get("title", ""))
            desc  = strip_tags(item.get("description", ""))
            if is_politics(title, desc):
                continue
            all_news["holdings"].append({
                "title":    title,
                "summary":  summarize(desc),
                "url":      item.get("originallink") or item.get("link", ""),
                "source":   "네이버뉴스",
                "category": "보유종목",
                "stock":    stock["name"],
                "date":     parse_naver_date(item.get("pubDate", "")),
            })
        time.sleep(0.3)  # API 과호출 방지

    all_news["holdings"] = deduplicate(all_news["holdings"])
    print(f"[보유종목 뉴스] {len(all_news['holdings'])}건 수집")

    print("[본문추출] 보유종목 뉴스 본문 가져오는 중...")
    enrich_full_text(all_news["holdings"])

    # 2. IT/과학 RSS 뉴스
    for feed in RSS_FEEDS:
        print(f"[RSS] {feed['name']} 수집중...")
        items = parse_rss(feed, max_items=8)
        all_news["tech"].extend(items)
        time.sleep(0.2)

    all_news["tech"] = deduplicate(all_news["tech"])
    # 최신순 정렬
    all_news["tech"].sort(key=lambda x: x["date"], reverse=True)
    all_news["tech"] = all_news["tech"][:50]  # 최대 50건만 유지
    print(f"[IT/과학 뉴스] {len(all_news['tech'])}건 수집")

    print("[본문추출] IT/과학 뉴스 본문 가져오는 중...")
    enrich_full_text(all_news["tech"])

    # 3. 야후 파이낸스 헤드라인
    print("[야후파이낸스] 헤드라인 수집중...")
    all_news["trends"] = parse_rss(YAHOO_FINANCE_FEED, max_items=8)
    all_news["trends"] = deduplicate(all_news["trends"])
    print(f"[야후파이낸스] {len(all_news['trends'])}건 수집")

    print("[본문추출] 야후파이낸스 본문 가져오는 중...")
    enrich_full_text(all_news["trends"])

    # 4. 일본어 학습 (청공문고 소설 하루 한 페이지, 정적 데이터 순환 — 네트워크 호출 없음)
    print("[일본어학습] 오늘의 페이지 선택중...")
    reading = get_daily_reading()
    all_news["japanese"] = [reading] if reading else []
    print(f"[일본어학습] {reading['page']}/{reading['total_pages']}페이지" if reading else "[일본어학습] 실패")

    # 5. JSON 저장
    output_path = os.path.join(os.path.dirname(__file__), "news.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print(f"\n[완료] news.json 저장 ({len(all_news['holdings'])}건 보유종목 + {len(all_news['tech'])}건 IT/과학 + {len(all_news['trends'])}건 경제(야후파이낸스) + {len(all_news['japanese'])}건 일본어)")

if __name__ == "__main__":
    main()
