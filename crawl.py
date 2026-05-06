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

# ── 설정 ──────────────────────────────────────────────────
NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

HOLDINGS_API_URL = "http://168.107.56.144:5000/api/data"

KST = timezone(timedelta(hours=9))

# 정치 블랙리스트 키워드
POLITICS_BLACKLIST = [
    "대통령", "국회", "여당", "야당", "민주당", "국민의힘", "정의당",
    "정치", "선거", "탄핵", "의원", "국무총리", "장관", "청와대",
    "대선", "총선", "지방선거", "공천", "당대표", "원내대표",
    "보수", "진보", "좌파", "우파", "집권", "야권", "여권",
]

# RSS 피드 목록 (IT/과학/의료/기이)
RSS_FEEDS = [
    # 국내 IT
    {"name": "전자신문",    "url": "https://www.etnews.com/rss/allnews.xml",           "category": "IT"},
    {"name": "ZDNet Korea", "url": "https://feeds.feedburner.com/zdkorea",              "category": "IT"},
    {"name": "IT조선",      "url": "https://it.chosun.com/rss/allArticle.xml",          "category": "IT"},
    {"name": "디지털데일리", "url": "http://www.ddaily.co.kr/rss/allArticle.xml",       "category": "IT"},
    {"name": "AI타임스",    "url": "https://www.aitimes.com/rss/allArticle.xml",        "category": "IT"},
    # 국내 과학
    {"name": "헬로디디",    "url": "https://www.hellodd.com/rss/allArticle.xml",        "category": "과학"},
    # 국내 의료/생명과학
    {"name": "코메디닷컴",  "url": "https://kormedi.com/feed/",                         "category": "의료"},
    {"name": "헬스조선",    "url": "https://health.chosun.com/rss/allArticle.xml",      "category": "의료"},
    # 해외 IT (영문)
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/",       "category": "IT"},
    {"name": "Ars Technica",   "url": "https://feeds.arstechnica.com/arstechnica/index", "category": "IT"},
    {"name": "The Verge",      "url": "https://www.theverge.com/rss/index.xml",        "category": "IT"},
    {"name": "WIRED",          "url": "https://www.wired.com/feed/rss",                "category": "IT"},
    # 해외 과학 (영문)
    {"name": "ScienceDaily",   "url": "https://www.sciencedaily.com/rss/all.xml",      "category": "과학"},
    {"name": "New Scientist",  "url": "https://www.newscientist.com/feed/home/",       "category": "과학"},
    {"name": "Live Science",   "url": "https://www.livescience.com/feeds/all",         "category": "과학"},
    {"name": "NASA News",      "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss","category": "과학"},
    # 해외 의료/생명과학 (영문 - 일반 독자용)
    {"name": "Medical Xpress", "url": "https://medicalxpress.com/rss-feed/",           "category": "의료"},
    {"name": "WebMD Health",   "url": "https://rssfeeds.webmd.com/rss/rss.aspx?RSSSource=RS_RSSFEEDS_ALLNEWS", "category": "의료"},
    {"name": "BBC Health",     "url": "https://feeds.bbci.co.uk/news/health/rss.xml",  "category": "의료"},
    {"name": "Healthline",     "url": "https://www.healthline.com/rss/news",           "category": "의료"},
    # 해외 기이한사건 (영문)
    {"name": "Oddity Central", "url": "https://www.odditycentral.com/feed",            "category": "기이"},
    {"name": "Boing Boing",    "url": "https://boingboing.net/feed",                   "category": "기이"},
    {"name": "Atlas Obscura",  "url": "https://www.atlasobscura.com/feeds/latest",     "category": "기이"},
    {"name": "Mysterious Univ","url": "https://mysteriousuniverse.org/feed/",          "category": "기이"},
    # 해외 흥미 (영문)
    {"name": "Interesting Eng","url": "https://interestingengineering.com/feed",        "category": "흥미"},
    {"name": "Futurism",       "url": "https://futurism.com/feed",                     "category": "흥미"},
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
    try:
        req = urllib.request.Request(HOLDINGS_API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
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

            items.append({
                "title":    title,
                "summary":  summarize(desc),
                "url":      link.strip(),
                "source":   feed_info["name"],
                "category": feed_info["category"],
                "date":     pub_date,
            })
            count += 1

    except Exception as e:
        print(f"[RSS] {feed_info['name']} 실패: {e}")

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
    all_news["tech"] = all_news["tech"][:100]  # 최대 100건만 유지
    print(f"[IT/과학 뉴스] {len(all_news['tech'])}건 수집")

    # 3. JSON 저장
    output_path = os.path.join(os.path.dirname(__file__), "news.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print(f"\n[완료] news.json 저장 ({len(all_news['holdings'])}건 보유종목 + {len(all_news['tech'])}건 IT/과학)")

if __name__ == "__main__":
    main()
