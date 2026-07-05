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

def summarize(text, length=120):
    """본문 앞부분 잘라서 요약"""
    clean = strip_tags(text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if len(clean) <= length:
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
    """RSS 피드 파싱 (표준 라이브러리만 사용)"""
    items = []
    try:
        req = urllib.request.Request(feed_info["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            raw = res.read().decode("utf-8", errors="replace")

        # title 추출
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', raw, re.DOTALL)
        descs  = re.findall(r'<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>', raw, re.DOTALL)
        links  = re.findall(r'<link>(https?://[^<]+)</link>', raw)
        dates  = re.findall(r'<pubDate>(.*?)</pubDate>', raw)

        # 첫 번째는 채널 title이라 스킵
        titles = titles[1:]
        descs  = descs[1:]

        count = 0
        for i, (t1, t2) in enumerate(titles):
            if count >= max_items:
                break
            title = strip_tags((t1 or t2).strip())
            if not title:
                continue

            d1, d2 = descs[i] if i < len(descs) else ("", "")
            desc = strip_tags((d1 or d2).strip())
            link = links[i+1] if i+1 < len(links) else (links[i] if i < len(links) else "")
            date_raw = dates[i] if i < len(dates) else ""

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
                "url":      link.strip(),
                "source":   feed_info["name"],
                "category": feed_info["category"],
                "date":     pub_date,
            })
            count += 1

    except Exception as e:
        print(f"[RSS] {feed_info['name']} 실패: {e}")

    return items

# ── 구글 트렌드 (실시간 인기 검색어) ──────────────────────
GOOGLE_TRENDS_FEEDS = [
    {"geo": "KR", "label": "구글트렌드 KR", "lang": "ko"},
    {"geo": "US", "label": "구글트렌드 US", "lang": "en"},
]

def fetch_google_trends(feed_info, max_items=10):
    """구글 실시간 인기 검색어 RSS 파싱"""
    items = []
    try:
        url = f"https://trends.google.com/trending/rss?geo={feed_info['geo']}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            raw = res.read().decode("utf-8", errors="replace")

        blocks = re.findall(r'<item>(.*?)</item>', raw, re.DOTALL)

        count = 0
        for block in blocks:
            if count >= max_items:
                break

            m_title = re.search(r'<title>(.*?)</title>', block, re.DOTALL)
            keyword = strip_tags((m_title.group(1) if m_title else "").strip())
            if not keyword:
                continue

            m_traffic = re.search(r'<ht:approx_traffic>(.*?)</ht:approx_traffic>', block)
            traffic = m_traffic.group(1).strip() if m_traffic else ""

            m_date = re.search(r'<pubDate>(.*?)</pubDate>', block)
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(m_date.group(1).strip())
                pub_date = dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            except:
                pub_date = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

            m_news_title  = re.search(r'<ht:news_item_title>(.*?)</ht:news_item_title>', block, re.DOTALL)
            m_news_url    = re.search(r'<ht:news_item_url>(.*?)</ht:news_item_url>', block)
            m_news_source = re.search(r'<ht:news_item_source>(.*?)</ht:news_item_source>', block)

            news_title  = strip_tags((m_news_title.group(1) if m_news_title else "").strip())
            news_url    = (m_news_url.group(1).strip() if m_news_url else "")
            news_source = strip_tags((m_news_source.group(1) if m_news_source else "").strip())

            if is_politics(keyword, news_title):
                continue

            if feed_info.get("lang") == "en":
                keyword    = translate(keyword)
                news_title = translate(news_title)

            summary = f"실시간 검색량 {traffic} · {news_title}" if news_title else f"실시간 검색량 {traffic}"

            items.append({
                "title":    keyword,
                "summary":  summary,
                "url":      news_url or f"https://trends.google.com/trending?geo={feed_info['geo']}",
                "source":   news_source or feed_info["label"],
                "category": "트렌드",
                "date":     pub_date,
            })
            count += 1

    except Exception as e:
        print(f"[구글트렌드] {feed_info['label']} 실패: {e}")

    return items

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
        "trends":   [],   # 실시간 인기 검색어
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

    # 3. 구글 실시간 트렌드
    for feed in GOOGLE_TRENDS_FEEDS:
        print(f"[구글트렌드] {feed['label']} 수집중...")
        items = fetch_google_trends(feed, max_items=10)
        all_news["trends"].extend(items)
        time.sleep(0.2)

    all_news["trends"] = deduplicate(all_news["trends"])
    print(f"[구글트렌드] {len(all_news['trends'])}건 수집")

    # 4. JSON 저장
    output_path = os.path.join(os.path.dirname(__file__), "news.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print(f"\n[완료] news.json 저장 ({len(all_news['holdings'])}건 보유종목 + {len(all_news['tech'])}건 IT/과학 + {len(all_news['trends'])}건 트렌드)")

if __name__ == "__main__":
    main()
