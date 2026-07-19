from flask import Flask, send_from_directory, jsonify, request, session, redirect, url_for, render_template_string
import json
import os
import time
from functools import wraps
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5003)
