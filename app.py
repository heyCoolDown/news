from flask import Flask, send_from_directory, jsonify, request, session, redirect, url_for, render_template_string
import json
import os
import time
import requests as req
from functools import wraps
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from deep_translator import GoogleTranslator
    _translator = GoogleTranslator(source='auto', target='ko')
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False


def translate(text):
    if not TRANSLATION_AVAILABLE or not text:
        return ''
    try:
        return _translator.translate(text[:4500]) or ''
    except Exception:
        return ''


def _load_dotenv():
    env_path = os.path.join(BASE_DIR, ".env")
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

app = Flask(__name__, static_folder=None)

LOGIN_FAIL_FILE = os.path.join(BASE_DIR, '.login_fails.json')

app.secret_key = os.environ.get('APP_KEY', 'fallback-secret-change-me')
app.permanent_session_lifetime = timedelta(days=30)
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')

# ── 로그인 시도 제한 (IP당 5회 실패 시 15분 잠금) ──
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SEC = 900


def _client_ip():
    return request.headers.get('X-Real-IP', request.remote_addr)


def _load_fails():
    if not os.path.exists(LOGIN_FAIL_FILE):
        return {}
    try:
        with open(LOGIN_FAIL_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_fails(data):
    tmp = LOGIN_FAIL_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, LOGIN_FAIL_FILE)


def _recent_fails(data, ip):
    now = time.time()
    return [t for t in data.get(ip, []) if now - t < LOGIN_LOCKOUT_SEC]


def _is_locked_out(ip):
    return len(_recent_fails(_load_fails(), ip)) >= LOGIN_MAX_ATTEMPTS


def _record_fail(ip):
    data = _load_fails()
    fails = _recent_fails(data, ip)
    fails.append(time.time())
    data[ip] = fails
    _save_fails(data)


def _clear_fails(ip):
    data = _load_fails()
    if ip in data:
        del data[ip]
        _save_fails(data)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('authed'):
            return f(*args, **kwargs)
        if request.path.startswith('/api/'):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for('login', next=request.path))
    return decorated


LOGIN_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>로그인 — 뉴스 대시보드</title>
<style>
  body{background:#0f172a;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-family:sans-serif}
  .box{background:#1e293b;padding:2rem 2.5rem;border-radius:12px;width:320px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
  h2{color:#f1f5f9;margin:0 0 1.5rem;text-align:center;font-size:1.1rem}
  input{width:100%;padding:.75rem 1rem;border:1px solid #334155;border-radius:8px;background:#0f172a;color:#f1f5f9;font-size:1rem;box-sizing:border-box}
  button{width:100%;margin-top:1rem;padding:.75rem;background:#3b82f6;color:#fff;border:none;border-radius:8px;font-size:1rem;cursor:pointer}
  button:hover{background:#2563eb}
  .err{color:#f87171;font-size:.85rem;margin-top:.75rem;text-align:center}
</style>
</head>
<body>
<div class="box">
  <h2>📰 뉴스 대시보드</h2>
  <form method="post">
    <input type="password" name="password" placeholder="비밀번호" autofocus>
    <button type="submit">접속</button>
    {% if error %}<p class="err">{{ error }}</p>{% endif %}
  </form>
</div>
</body>
</html>"""


@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = _client_ip()
    if _is_locked_out(ip):
        return render_template_string(
            LOGIN_HTML, error=f'{LOGIN_MAX_ATTEMPTS}회 실패로 {LOGIN_LOCKOUT_SEC // 60}분간 잠겼습니다'
        )
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            _clear_fails(ip)
            session['authed'] = True
            session.permanent = True
            return redirect(request.args.get('next') or '/')
        _record_fail(ip)
        return render_template_string(LOGIN_HTML, error='비밀번호가 틀렸습니다')
    return render_template_string(LOGIN_HTML, error=None)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@require_auth
def index():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/news.json')
@require_auth
def news_json():
    return send_from_directory(BASE_DIR, 'news.json')


# ── Serenity(X @aleabitoreddit) 트윗 피드 ────────────────────────────
# 오라클 미러 전용(require_auth) — GitHub Actions(crawl.py)나 news.json에는
# 절대 넣지 않는다. news 저장소는 Public이라 3rd-party 저작권 콘텐츠를
# 커밋하면 비번게이트와 무관하게 노출되기 때문 (.serenity_cache.json은 .gitignore 처리).
SERENITY_URL = 'https://www.trackserenity.com/data/signals.json'
SERENITY_CACHE_FILE = os.path.join(BASE_DIR, '.serenity_cache.json')
SERENITY_TTL_SEC = 6 * 3600


def _fetch_serenity():
    try:
        res = req.get(SERENITY_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = res.json()
        tweets = data.get('tweets', [])[:20]
        items = [{
            'id':         t.get('id'),
            'text':       t.get('text', ''),
            'text_ko':    translate(t.get('text', '')),
            'url':        t.get('url', ''),
            'time':       t.get('displayTime', ''),
            'cashtags':   t.get('cashtags', []),
            'is_retweet': t.get('isRetweet', False),
        } for t in tweets]
        return {'items': items, 'source_updated': data.get('updatedAt', ''), 'fetched_at': time.time()}
    except Exception:
        return {'items': [], 'source_updated': '', 'fetched_at': time.time()}


@app.route('/api/serenity')
@require_auth
def api_serenity():
    cached = None
    if os.path.exists(SERENITY_CACHE_FILE):
        try:
            with open(SERENITY_CACHE_FILE, encoding='utf-8') as f:
                cached = json.load(f)
        except Exception:
            cached = None
    if not cached or time.time() - cached.get('fetched_at', 0) > SERENITY_TTL_SEC:
        cached = _fetch_serenity()
        tmp = SERENITY_CACHE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cached, f, ensure_ascii=False)
        os.replace(tmp, SERENITY_CACHE_FILE)
    return jsonify(cached)


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5003)
