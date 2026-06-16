"""
K-ALPHA 유저 서비스 앱
- 회원가입/로그인: Google · 카카오 · 네이버 OAuth
- 결제: 토스페이먼츠 테스트 모드
- 쿠폰: 7일 무료 쿠폰
- 법적 동의 후 종목 뷰 제공 (관리자 기능 완전 숨김)
"""

import streamlit as st
import streamlit.components.v1 as components
import requests, json, time, secrets, hashlib, uuid
from datetime import datetime, timedelta, timezone
import urllib.parse

st.set_page_config(
    page_title="K-ALPHA",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 환경변수 / Secrets ──────────────────────────────────────────
def _s(key, default=""):
    try: return st.secrets.get(key, default) or default
    except: return default

SUPABASE_URL      = _s("SUPABASE_URL")
SUPABASE_KEY      = _s("SUPABASE_SERVICE_KEY")   # service_role key (백엔드 전용)
TG_BOT_TOKEN      = _s("TG_BOT_TOKEN")
TG_GROUP1_CHAT    = _s("TG_GROUP1_CHAT") or _s("TG_ADMIN_CHAT")  # 관리자 승인 그룹방1
TG_GROUP2_INVITE  = _s("TG_GROUP2_INVITE")                        # VIP 방2 초대링크
TG_ADMIN_CHAT     = TG_GROUP1_CHAT
GIST_ID           = _s("GIST_ID")
TOSS_CLIENT_KEY   = _s("TOSS_CLIENT_KEY")         # 토스 테스트 클라이언트 키
TOSS_SECRET_KEY   = _s("TOSS_SECRET_KEY")         # 토스 테스트 시크릿 키
GOOGLE_CLIENT_ID  = _s("GOOGLE_CLIENT_ID")
GOOGLE_SECRET     = _s("GOOGLE_SECRET") or _s("GOOGLE_CLIENT_SECRET")
KAKAO_CLIENT_ID   = _s("KAKAO_CLIENT_ID")
NAVER_CLIENT_ID   = _s("NAVER_CLIENT_ID")
NAVER_SECRET      = _s("NAVER_SECRET")
ADMIN_EMAILS      = [e.strip() for e in _s("ADMIN_EMAILS","").split(",") if e.strip()]

APP_URL = _s("USER_APP_URL", "http://localhost:8501")   # 배포 후 실제 URL로 변경
LEGAL_VERSION = "v1"
PLAN_PRICE = {"monthly": 33000, "yearly": 363000}
PLAN_LABEL = {"monthly": "월정액 33,000원", "yearly": "연간 363,000원 (1개월 무료)"}

# ── Supabase 헬퍼 ──────────────────────────────────────────────
def _sb(method, path, body=None, params=None):
    """Supabase REST API 호출"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    try:
        r = getattr(requests, method)(url, headers=headers, json=body, params=params, timeout=10)
        if r.status_code == 204: return []          # DELETE 성공 (빈 응답)
        if r.status_code in (200, 201): return r.json()
        st.warning(f"Supabase 오류 [{r.status_code}]: {r.text[:200]}")
        return None
    except Exception as e:
        st.warning(f"Supabase 예외: {e}")
        return None

def sb_upsert_user(email, name, provider, provider_id, avatar=""):
    """유저 없으면 생성, 있으면 last_login 갱신"""
    existing = _sb("get", "users", params={"email": f"eq.{email}", "select": "id,email,name"})
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        _sb("patch", f"users?email=eq.{urllib.parse.quote(email)}",
            body={"last_login": now, "name": name or existing[0].get("name")})
        return existing[0]["id"]
    res = _sb("post", "users", body={
        "email": email, "name": name, "provider": provider,
        "provider_id": str(provider_id), "avatar_url": avatar,
        "created_at": now, "last_login": now,
    })
    return res[0]["id"] if res else None

def sb_get_active_sub(user_id):
    """활성 구독 조회"""
    now = datetime.now(timezone.utc).isoformat()
    rows = _sb("get", "subscriptions", params={
        "user_id": f"eq.{user_id}",
        "status":  "eq.active",
        "expires_at": f"gt.{now}",
        "order": "expires_at.desc",
        "limit": "1",
    })
    return rows[0] if rows else None

def sb_create_sub(user_id, plan, days):
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=days)).isoformat()
    return _sb("post", "subscriptions", body={
        "user_id": str(user_id), "plan": plan,
        "status": "active", "starts_at": now.isoformat(), "expires_at": expires,
    })

def sb_check_legal(user_id):
    rows = _sb("get", "legal_agreements", params={
        "user_id": f"eq.{user_id}", "version": f"eq.{LEGAL_VERSION}", "limit": "1"
    })
    return bool(rows)

def sb_agree_legal(user_id):
    _sb("post", "legal_agreements", body={"user_id": str(user_id), "version": LEGAL_VERSION})

def sb_use_coupon(code, user_id):
    """쿠폰 검증 및 사용. (days, error_msg) 반환"""
    rows = _sb("get", "coupons", params={"code": f"eq.{code.upper()}", "limit": "1"})
    if not rows: return None, "존재하지 않는 쿠폰입니다"
    c = rows[0]
    now = datetime.now(timezone.utc)
    if c.get("expires_at") and now > datetime.fromisoformat(c["expires_at"].replace("Z", "+00:00")):
        return None, "만료된 쿠폰입니다"
    if c.get("use_count", 0) >= c.get("max_uses", 1):
        return None, "이미 사용된 쿠폰입니다"
    # 사용 처리
    _sb("patch", f"coupons?code=eq.{code.upper()}", body={
        "used_by": str(user_id), "used_at": now.isoformat(),
        "use_count": c.get("use_count", 0) + 1,
    })
    return c.get("duration_days", 7), None

def sb_check_expiry_notify():
    """만료 2일 전 유저 조회 → 관리자 그룹1에 알림"""
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(days=2)).isoformat()
    tomorrow = (now + timedelta(days=3)).isoformat()
    rows = _sb("get", "subscriptions", params={
        "status": "eq.active",
        "expires_at": f"lt.{soon}",
        "select": "user_id,expires_at",
    }) or []
    for r in rows:
        u = (_sb("get", "users", params={"id": f"eq.{r['user_id']}", "select": "email,name", "limit": "1"}) or [{}])[0]
        exp = r.get("expires_at","")[:10]
        send_tg_admin(
            f"⚠️ <b>구독 만료 2일 전 알림</b>\n"
            f"👤 {u.get('name','')} ({u.get('email','')})\n"
            f"📅 만료일: {exp}\n"
            f"💡 갱신 안내 필요"
        )

def sb_get_tg_request(user_id):
    rows = _sb("get", "tg_join_requests", params={"user_id": f"eq.{user_id}", "limit": "1"})
    return rows[0] if rows else None

def sb_create_tg_request(user_id):
    return _sb("post", "tg_join_requests", body={
        "user_id": str(user_id), "status": "pending",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })

def send_tg_admin(text):
    if not TG_BOT_TOKEN or not TG_ADMIN_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_ADMIN_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except: pass

def sb_save_payment(user_id, order_id, amount, plan, payment_key=None, status="pending", raw=None):
    if status == "done":
        _sb("patch", f"payments?order_id=eq.{order_id}", body={
            "payment_key": payment_key, "status": "done",
            "paid_at": datetime.now(timezone.utc).isoformat(),
            "raw": raw or {},
        })
    else:
        _sb("post", "payments", body={
            "user_id": str(user_id), "order_id": order_id,
            "amount": amount, "plan": plan, "status": "pending",
        })

# ── OAuth 헬퍼 ─────────────────────────────────────────────────
def _oauth_redirect_uri(provider):
    return f"{APP_URL}?oauth={provider}"

def google_auth_url():
    params = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": st.session_state.get("oauth_state", ""),
        "access_type": "offline",
        "prompt": "select_account",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

def kakao_auth_url():
    params = urllib.parse.urlencode({
        "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("kakao"),
        "response_type": "code",
        "state": st.session_state.get("oauth_state", ""),
    })
    return f"https://kauth.kakao.com/oauth/authorize?{params}"

def naver_auth_url():
    params = urllib.parse.urlencode({
        "client_id": NAVER_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("naver"),
        "response_type": "code",
        "state": st.session_state.get("oauth_state", ""),
    })
    return f"https://nid.naver.com/oauth2.0/authorize?{params}"

def exchange_google(code):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_SECRET,
        "redirect_uri": _oauth_redirect_uri("google"), "grant_type": "authorization_code",
    }, timeout=10)
    rj = r.json()
    token = rj.get("access_token")
    if not token:
        st.error(f"Google 토큰 오류: {rj.get('error','')}: {rj.get('error_description','')}")
        return None
    info = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    return {"email": info.get("email"), "name": info.get("name"),
            "provider_id": info.get("id"), "avatar": info.get("picture", "")}

def exchange_kakao(code):
    r = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "authorization_code", "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("kakao"), "code": code,
    }, timeout=10)
    token = r.json().get("access_token")
    if not token: return None
    info = requests.get("https://kapi.kakao.com/v2/user/me",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    kakao_acct = info.get("kakao_account", {})
    profile = kakao_acct.get("profile", {})
    return {"email": kakao_acct.get("email", f"kakao_{info['id']}@kakao.local"),
            "name": profile.get("nickname", ""),
            "provider_id": str(info["id"]),
            "avatar": profile.get("thumbnail_image_url", "")}

def exchange_naver(code, state):
    r = requests.post("https://nid.naver.com/oauth2.0/token", params={
        "grant_type": "authorization_code", "client_id": NAVER_CLIENT_ID,
        "client_secret": NAVER_SECRET, "code": code, "state": state,
    }, timeout=10)
    token = r.json().get("access_token")
    if not token: return None
    info = requests.get("https://openapi.naver.com/v1/nid/me",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    res = info.get("response", {})
    return {"email": res.get("email", f"naver_{res.get('id','?')}@naver.local"),
            "name": res.get("name", ""),
            "provider_id": res.get("id", ""),
            "avatar": res.get("profile_image", "")}

# ── Toss 결제 확인 ─────────────────────────────────────────────
def toss_confirm(payment_key, order_id, amount):
    import base64
    auth = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    r = requests.post(
        f"https://api.tosspayments.com/v1/payments/confirm",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
        timeout=15,
    )
    return r.json()

# ── Gist 스캔 데이터 ───────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def load_scan_data():
    if not GIST_ID: return None
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}",
                         headers={"Accept": "application/vnd.github.v3+json"}, timeout=5)
        content = r.json().get("files", {}).get("kalpha_scan.json", {}).get("content", "")
        return json.loads(content) if content else None
    except: return None

# ── 공통 CSS ───────────────────────────────────────────────────
def inject_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');
* { font-family: 'Noto Sans KR', sans-serif; box-sizing: border-box; }
body, .stApp { background: #0a0e1a; color: #e2e8f0; }
.stApp > header { display: none; }
[data-testid="stSidebar"] { display: none; }
/* 버튼 */
.stButton > button {
    border-radius: 10px; font-weight: 600; transition: all .2s;
    border: none; cursor: pointer;
}
/* 소셜 버튼 */
.social-btn {
    display: flex; align-items: center; justify-content: center; gap: 10px;
    padding: 12px 20px; border-radius: 12px; font-size: 15px; font-weight: 600;
    cursor: pointer; width: 100%; border: none; margin: 6px 0; transition: all .2s;
}
.btn-google { background: #fff; color: #333; }
.btn-kakao  { background: #FEE500; color: #3A1D1D; }
.btn-naver  { background: #03C75A; color: #fff; }
.social-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 16px rgba(0,0,0,.3); }
/* 카드 */
.card {
    background: #141929; border: 1px solid #1e2a3a;
    border-radius: 14px; padding: 18px; margin: 8px 0;
}
/* 탭 */
.tab-bar {
    display: flex; gap: 4px; overflow-x: auto; padding: 4px 0;
    scrollbar-width: none; border-bottom: 1px solid #1e2a3a; margin-bottom: 16px;
}
.tab-bar::-webkit-scrollbar { display: none; }
.tab-item {
    padding: 8px 16px; border-radius: 8px 8px 0 0; white-space: nowrap;
    cursor: pointer; font-size: 13px; font-weight: 600; color: #64748b;
    border: 1px solid transparent; border-bottom: none;
}
.tab-item.active { color: #00d4ff; border-color: #1e2a3a; background: #141929; }
/* 가격 카드 */
.price-card {
    background: #141929; border: 2px solid #1e2a3a; border-radius: 16px;
    padding: 24px; text-align: center; transition: all .2s;
}
.price-card.featured { border-color: #00d4ff; }
.price-card:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,212,255,.1); }
/* 종목 카드 */
.stock-card {
    background: #141929; border: 1px solid #1e2a3a; border-radius: 14px;
    padding: 16px; margin: 8px 0; transition: border-color .2s;
}
.stock-card:hover { border-color: #00d4ff44; }
.pos { color: #ff3b5c; } .neg { color: #4fa3e0; }
input[type=text] { border-radius: 8px !important; }
</style>
""", unsafe_allow_html=True)

# ── 로그인 페이지 ──────────────────────────────────────────────
TELEGRAM_JOIN_URL = "https://t.me/your_channel"  # 실제 텔레그램 링크로 교체

def _get_bg_base64():
    import base64, os
    path = os.path.join(os.path.dirname(__file__), "bg.png")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(__file__), "이미지2.png")
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except:
        return ""

def page_login():
    gurl = google_auth_url() if GOOGLE_CLIENT_ID else "#"
    kurl = kakao_auth_url()  if KAKAO_CLIENT_ID  else "#"
    nurl = naver_auth_url()  if NAVER_CLIENT_ID   else "#"

    google_btn = f"""
<a href="{gurl}" style="text-decoration:none;display:block;margin-top:10px">
<div style="display:flex;align-items:center;justify-content:center;gap:12px;
  background:#fff;color:#3c4043;border-radius:8px;padding:14px 20px;
  font-size:16px;font-weight:600;cursor:pointer;border:none;width:100%;box-sizing:border-box;">
  <svg width="22" height="22" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.14 0 5.95 1.08 8.17 2.86L38.53 6C34.46 2.29 29.52 0 24 0 14.62 0 6.51 5.56 2.69 13.65l7.37 5.72C11.95 13.02 17.51 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.36-8.16 2.36-6.48 0-11.97-4.37-13.93-10.26l-7.98 6.19C6.51 42.44 14.62 48 24 48z"/><path fill="none" d="M0 0h48v48H0z"/></svg>
  Google로 계속하기
</div></a>""" if GOOGLE_CLIENT_ID else ""

    kakao_btn = f"""
<a href="{kurl}" style="text-decoration:none;display:block;margin-top:10px">
<div style="display:flex;align-items:center;justify-content:center;gap:12px;
  background:#FEE500;color:#3A1D1D;border-radius:8px;padding:14px 20px;
  font-size:16px;font-weight:600;cursor:pointer;width:100%;box-sizing:border-box;">
  <svg width="22" height="22" viewBox="0 0 24 24"><path fill="#3A1D1D" d="M12 3C6.48 3 2 6.58 2 11c0 2.79 1.65 5.24 4.13 6.76L5.25 21l4.05-2.16c.88.21 1.77.16 2.7.16 5.52 0 10-3.58 10-8S17.52 3 12 3z"/></svg>
  카카오로 계속하기
</div></a>""" if KAKAO_CLIENT_ID else ""

    naver_btn = f"""
<a href="{nurl}" style="text-decoration:none;display:block;margin-top:10px">
<div style="display:flex;align-items:center;justify-content:center;gap:12px;
  background:#03C75A;color:#fff;border-radius:8px;padding:14px 20px;
  font-size:16px;font-weight:600;cursor:pointer;width:100%;box-sizing:border-box;">
  <span style="font-size:20px;font-weight:900;line-height:1">N</span>
  네이버로 계속하기
</div></a>""" if NAVER_CLIENT_ID else ""

    bg64 = _get_bg_base64()
    bg_style = (
        f"background:url('data:image/png;base64,{bg64}') center center/cover no-repeat fixed;"
        if bg64 else
        "background:linear-gradient(160deg,#050810 0%,#0d1526 50%,#050810 100%);"
    )
    st.markdown(f"""
<style>
  .stApp {{ background: #0a0e1a; }}
  #MainMenu, footer, header {{ visibility: hidden; }}
</style>
<div style="min-height:100vh;{bg_style}
  display:flex;align-items:center;justify-content:center;padding:40px 16px;box-sizing:border-box;
  position:relative;">
<div style="position:absolute;inset:0;background:rgba(5,8,16,0.55);pointer-events:none"></div>
<div style="width:100%;max-width:420px;text-align:center;position:relative;z-index:1;">

  <!-- 헤드라인 -->
  <div style="font-size:26px;font-weight:800;color:#c9a84c;line-height:1.35;margin-bottom:24px;
    text-shadow:0 0 20px rgba(201,168,76,0.4);">
    단 한 번의 투자로<br>1%의 엘리트에 합류하세요.
  </div>

  <!-- 로고 -->
  <div style="margin-bottom:6px;">
    <span style="font-size:32px;font-weight:900;letter-spacing:2px;
      background:linear-gradient(135deg,#c9a84c,#f5d98b,#c9a84c);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
      케이·알파
    </span>
  </div>
  <div style="font-size:15px;font-weight:700;color:#8899bb;letter-spacing:4px;margin-bottom:4px;">K-ALPHA</div>
  <div style="display:inline-block;border:1px solid #c9a84c44;border-radius:20px;
    padding:3px 14px;font-size:12px;color:#c9a84c;margin-bottom:28px;">국내 주식 공유</div>

  <!-- 텔레그램 박스 -->
  <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(201,168,76,0.25);
    border-radius:14px;padding:20px;margin-bottom:20px;">
    <div style="font-size:14px;color:#aabbcc;line-height:1.6;margin-bottom:16px;">
      최신 정보 및 특별 혜택을 위한<br>
      <span style="color:#f5d98b;font-weight:600;">텔레그램 프리미엄 공유방</span>에 참여하세요
    </div>
    <a href="{TELEGRAM_JOIN_URL}" target="_blank" style="text-decoration:none;">
    <div style="display:flex;align-items:center;justify-content:center;gap:12px;
      background:linear-gradient(135deg,#1a2744,#243357);
      border:1px solid #2a4080;border-radius:10px;padding:14px;cursor:pointer;">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="#29B6F6">
        <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/>
      </svg>
      <span style="color:#fff;font-size:15px;font-weight:600;">참여 신청</span>
    </div></a>
  </div>

  <!-- 로그인 박스 -->
  <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(201,168,76,0.2);
    border-radius:14px;padding:20px;">
    <div style="font-size:13px;color:#c9a84c;font-weight:600;margin-bottom:4px;">
      당신의 특별한 접근 권한 - 멤버십 인증 후 입장
    </div>
    <div style="font-size:12px;color:#667788;margin-bottom:16px;">멤버십 가입 및 로그인으로 엑세스</div>
    {google_btn}
    {kakao_btn}
    {naver_btn}
  </div>

</div>
</div>
""", unsafe_allow_html=True)

# ── 구독/결제 페이지 ──────────────────────────────────────────
def page_subscribe(user):
    user_id = user["id"]
    email   = user["email"]
    name    = user.get("name", "")

    st.markdown(f"""
<div style="text-align:center;padding:40px 0 20px">
<div style="font-size:28px;font-weight:800">
  <span style="color:#00d4ff">K</span>·<span style="color:#fff">ALPHA</span> 구독
</div>
<div style="color:#64748b;margin-top:6px">안녕하세요, {name or email}님</div>
</div>
""", unsafe_allow_html=True)

    tab_pay, tab_coupon = st.tabs(["💳 결제", "🎫 무료 쿠폰"])

    # ── 결제 탭 ──
    with tab_pay:
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            st.markdown("""
<div class="price-card">
  <div style="font-size:13px;color:#64748b;margin-bottom:8px">월정액</div>
  <div style="font-size:32px;font-weight:800;color:#e2e8f0">33,000<span style="font-size:16px">원</span></div>
  <div style="font-size:12px;color:#64748b;margin:4px 0 20px">VAT 포함 · 매월 자동결제</div>
  <ul style="text-align:left;color:#94a3b8;font-size:13px;padding-left:18px;line-height:2">
    <li>실시간 종목 스캔</li>
    <li>스윙·급등·내일관심·중소형주</li>
    <li>K 점수 & 분석 사유</li>
  </ul>
</div>
""", unsafe_allow_html=True)
            if st.button("월정액 구독", use_container_width=True, key="btn_monthly"):
                st.session_state["pending_plan"] = "monthly"
                st.session_state["pending_amount"] = 33000
                st.rerun()

        with col2:
            st.markdown("""
<div class="price-card featured">
  <div style="font-size:13px;color:#00d4ff;margin-bottom:8px">✨ 연간 · 1개월 무료</div>
  <div style="font-size:32px;font-weight:800;color:#e2e8f0">363,000<span style="font-size:16px">원</span></div>
  <div style="font-size:12px;color:#64748b;margin:4px 0 20px">VAT 포함 · 월 30,250원 상당</div>
  <ul style="text-align:left;color:#94a3b8;font-size:13px;padding-left:18px;line-height:2">
    <li>월정액 모든 기능 포함</li>
    <li>1개월 추가 무료</li>
    <li>연 갱신 알림</li>
  </ul>
</div>
""", unsafe_allow_html=True)
            if st.button("연간 구독", use_container_width=True, type="primary", key="btn_yearly"):
                st.session_state["pending_plan"] = "yearly"
                st.session_state["pending_amount"] = 363000
                st.rerun()

        # 토스 결제 위젯
        if st.session_state.get("pending_plan"):
            plan   = st.session_state["pending_plan"]
            amount = st.session_state["pending_amount"]
            order_id = f"kalpha-{user_id[:8]}-{int(time.time())}"
            order_name = PLAN_LABEL[plan]
            success_url = f"{APP_URL}?pay_ok=1&plan={plan}"
            fail_url    = f"{APP_URL}?pay_fail=1"

            # DB에 pending 결제 기록
            sb_save_payment(user_id, order_id, amount, plan)

            toss_html = f"""
<!DOCTYPE html><html><head>
<script src="https://js.tosspayments.com/v1/payment"></script>
</head><body style="margin:0;padding:16px;background:#0a0e1a;font-family:sans-serif">
<button onclick="pay()" style="
  width:100%;padding:18px;
  background:linear-gradient(135deg,#00d4ff,#0099cc);
  color:#0a0e1a;border:none;border-radius:12px;
  font-size:18px;font-weight:800;cursor:pointer;letter-spacing:-0.5px">
  💳 {amount:,}원 결제하기
</button>
<script>
const tossPayments = TossPayments('{TOSS_CLIENT_KEY}');
async function pay(){{
  try{{
    await tossPayments.requestPayment('카드', {{
      amount: {amount},
      orderId: '{order_id}',
      orderName: '{order_name}',
      successUrl: '{success_url}&orderId={order_id}&amount={amount}',
      failUrl: '{fail_url}',
      customerEmail: '{email}',
      customerName: '{name or "고객"}',
    }});
  }} catch(e) {{
    alert('결제 오류: ' + e.message);
  }}
}}
</script></body></html>"""
            st.markdown("---")
            st.markdown(f"**{order_name}** 결제를 진행합니다")
            components.html(toss_html, height=600, scrolling=True)

            if st.button("← 취소", key="btn_cancel_pay"):
                del st.session_state["pending_plan"]
                del st.session_state["pending_amount"]
                st.rerun()

    # ── 쿠폰 탭 ──
    with tab_coupon:
        st.markdown("""
<div style="max-width:400px;margin:20px auto;text-align:center">
  <div style="font-size:40px;margin-bottom:12px">🎫</div>
  <div style="font-size:18px;font-weight:700;margin-bottom:8px">무료 쿠폰</div>
  <div style="color:#64748b;font-size:13px;margin-bottom:24px">쿠폰 번호를 입력하면 7일간 무료로 이용할 수 있습니다</div>
</div>
""", unsafe_allow_html=True)
        coupon_code = st.text_input("쿠폰 번호", placeholder="예: KALPHA-XXXX-XXXX", max_chars=30,
                                    label_visibility="collapsed").strip().upper()
        if st.button("쿠폰 적용", use_container_width=True, type="primary", key="btn_coupon"):
            if not coupon_code:
                st.error("쿠폰 번호를 입력해주세요")
            else:
                days, err = sb_use_coupon(coupon_code, user_id)
                if err:
                    st.error(f"❌ {err}")
                else:
                    sb_create_sub(user_id, "coupon", days)
                    st.success(f"✅ {days}일 무료 이용이 시작됩니다!")
                    time.sleep(1)
                    st.session_state["sub"] = sb_get_active_sub(user_id)
                    st.rerun()

    # 로그아웃
    st.markdown("---")
    if st.button("로그아웃", key="btn_logout_sub"):
        for k in ["user","sub","legal"]:
            st.session_state.pop(k, None)
        st.rerun()

# ── 법적 고지 페이지 ──────────────────────────────────────────
def page_legal(user):
    st.markdown("""
<div style="max-width:600px;margin:40px auto">
<div style="font-size:22px;font-weight:800;margin-bottom:20px;text-align:center">
  📋 서비스 이용 약관 및 투자 위험 고지
</div>
<div class="card" style="font-size:13px;line-height:2;color:#94a3b8;max-height:400px;overflow-y:auto">
<b style="color:#e2e8f0">제1조 (서비스 목적)</b><br>
K-ALPHA는 국내 주식시장의 실시간 데이터를 분석하여 투자 참고 정보를 제공하는 서비스입니다.
본 서비스는 투자 권유가 아니며, 제공되는 모든 정보는 참고 목적으로만 활용되어야 합니다.<br><br>

<b style="color:#e2e8f0">제2조 (투자 위험 고지)</b><br>
· 주식 투자는 원금 손실의 위험이 있습니다.<br>
· 본 서비스의 분석 결과는 미래 수익을 보장하지 않습니다.<br>
· 투자 결정은 이용자 본인의 판단과 책임 하에 이루어져야 합니다.<br>
· 과거의 수익률이 미래의 수익률을 보장하지 않습니다.<br><br>

<b style="color:#e2e8f0">제3조 (자동매매 관련)</b><br>
· 자동매매 기능은 테스트 목적으로만 제공됩니다.<br>
· 실제 주문 실행에 따른 손익은 이용자 본인이 책임집니다.<br>
· 시스템 오류, 네트워크 장애 등으로 인한 손해에 대해 당사는 책임지지 않습니다.<br><br>

<b style="color:#e2e8f0">제4조 (개인정보 처리)</b><br>
· 이용자의 이메일, 이름 등 최소한의 정보만 수집합니다.<br>
· 수집된 정보는 서비스 제공 목적으로만 사용됩니다.<br>
· 제3자에게 개인정보를 제공하지 않습니다 (법령에 의한 경우 제외).<br><br>

<b style="color:#e2e8f0">제5조 (구독 및 환불)</b><br>
· 월정액: 결제일로부터 30일간 이용 가능합니다.<br>
· 연간: 결제일로부터 365일간 이용 가능합니다.<br>
· 환불: 이용 시작 7일 이내 미사용 시 전액 환불 가능합니다.<br><br>

<b style="color:#e2e8f0">제6조 (서비스 중단)</b><br>
당사는 시스템 점검, 업데이트 등의 이유로 사전 고지 후 서비스를 일시 중단할 수 있습니다.
</div>
</div>
""", unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        agreed = st.checkbox("위 약관 및 투자 위험 고지 내용을 모두 읽고 동의합니다", key="chk_legal")
        if st.button("동의하고 시작하기", disabled=not agreed, use_container_width=True,
                     type="primary", key="btn_legal_ok"):
            sb_agree_legal(user["id"])
            st.session_state["legal"] = True
            st.rerun()

# ── 메인 종목 뷰 ──────────────────────────────────────────────
def page_main(user, sub):
    expires = sub.get("expires_at","")
    try:
        exp_dt = datetime.fromisoformat(expires.replace("Z","+00:00"))
        days_left = (exp_dt - datetime.now(timezone.utc)).days
        exp_str = exp_dt.strftime("%Y.%m.%d")
    except:
        days_left = 0; exp_str = "?"

    # 상단 헤더
    col_l, col_r = st.columns([4,1])
    with col_l:
        st.markdown(f"""
<div style="padding:10px 0 4px;display:flex;align-items:center;gap:12px">
  <span style="font-size:22px;font-weight:900">
    <span style="color:#00d4ff">K</span>·<span style="color:#fff">ALPHA</span>
  </span>
  <span style="font-size:12px;color:#64748b">
    {user.get('name') or user.get('email','')} ·
    <span style="color:{'#00ff88' if days_left>7 else '#ffc800'}">
      {days_left}일 남음 ({exp_str} 만료)
    </span>
  </span>
</div>
""", unsafe_allow_html=True)
    with col_r:
        if st.button("로그아웃", key="btn_logout_main"):
            for k in ["user","sub","legal"]:
                st.session_state.pop(k, None)
            st.rerun()

    # VIP 텔레그램 참가 신청
    tg_req = sb_get_tg_request(user["id"])
    if not tg_req:
        st.markdown("""
<div style="background:linear-gradient(135deg,#1a2744,#243357);border:1px solid #2a4080;
  border-radius:12px;padding:16px 20px;margin-bottom:16px;display:flex;
  align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
  <div>
    <div style="color:#f5d98b;font-weight:700;font-size:15px;">📢 VIP 텔레그램 공유방</div>
    <div style="color:#8899bb;font-size:13px;margin-top:2px;">실시간 종목 알림 · 프리미엄 정보 공유</div>
  </div>
</div>
""", unsafe_allow_html=True)
        if st.button("✈️ VIP 텔레그램 참가 신청", key="btn_tg_join", type="primary"):
            sb_create_tg_request(user["id"])
            send_tg_admin(
                f"🔔 <b>VIP 텔레그램 참가 신청</b>\n"
                f"👤 이름: {user.get('name','(없음)')}\n"
                f"📧 이메일: {user.get('email','')}\n"
                f"📦 플랜: {sub.get('plan','')}\n"
                f"⏰ 신청 시각: {datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')}"
            )
            st.success("신청 완료! 관리자 확인 후 초대 링크를 보내드립니다.")
            st.rerun()
    elif tg_req.get("status") == "approved":
        st.success("✅ VIP 텔레그램 참가 승인 완료", icon="✅")
        if TG_GROUP2_INVITE:
            st.markdown(f"""
<a href="{TG_GROUP2_INVITE}" target="_blank" style="text-decoration:none">
<div style="background:linear-gradient(135deg,#1a2744,#243357);border:1px solid #2a4080;
  border-radius:10px;padding:14px 20px;text-align:center;color:#fff;font-weight:600;font-size:15px;cursor:pointer;">
  ✈️ VIP 텔레그램 방 입장하기
</div></a>""", unsafe_allow_html=True)
    else:
        st.info("⏳ VIP 텔레그램 참가 신청 검토 중입니다.", icon="📨")

    # 스캔 데이터 로드
    data = load_scan_data()
    if not data:
        st.info("📡 스캔 데이터를 불러오는 중입니다. 잠시 후 다시 시도해주세요.", icon="⏳")
        return

    total  = data.get("total", 0)
    ts     = data.get("ts","")
    kospi  = data.get("kospi_n", 0)
    kosdaq = data.get("kosdaq_n", 0)

    st.markdown(f"""
<div style="font-size:12px;color:#64748b;padding:4px 0 12px">
  📡 KOSPI {kospi} + KOSDAQ {kosdaq}종목 스캔 ·
  <span style="color:#00ff88">{ts} 업데이트</span>
</div>
""", unsafe_allow_html=True)

    # 카테고리 탭
    categories = [
        ("실시간 스윙주", "swing",    "🔴"),
        ("급등 전야",    "surge",    "⚡"),
        ("내일 관심주",  "tomorrow", "🌙"),
        ("중소형주",     "smallmid", "📦"),
        ("PER저평가",    "per",      "💎"),
    ]

    # 팝업 열기 상태
    popup_key = st.session_state.get("popup_cat", None)

    # 팝업이 열려 있으면 전체화면 오버레이로 종목 리스트 표시
    if popup_key:
        cat_info = {k: (n, icon) for n, k, icon in categories}
        if popup_key in cat_info:
            popup_name, popup_icon = cat_info[popup_key]
            popup_stocks = data.get(popup_key, [])
            col_title, col_close = st.columns([5,1])
            with col_title:
                st.markdown(f"""
<div style="font-size:20px;font-weight:800;color:#e2e8f0;padding:8px 0">
  {popup_icon} {popup_name}
  <span style="font-size:14px;color:#64748b;margin-left:8px">{len(popup_stocks)}종목</span>
</div>""", unsafe_allow_html=True)
            with col_close:
                if st.button("✕ 닫기", key="popup_close"):
                    st.session_state.pop("popup_cat", None)
                    st.rerun()
            # 종목 요약 리스트 — 하나의 st.markdown으로 렌더링 (DOM 불일치 방지)
            grade_colors = {"S":"#ff3b5c","A":"#ff9900","B":"#ffc800","C":"#94a3b8"}
            rows_html = ""
            for s in popup_stocks:
                n = s.get("name",""); c = s.get("code","")
                pr = s.get("price",""); ch = s.get("change","")
                chg_c = "#ff3b5c" if s.get("up", True) else "#4fa3e0"
                sc = s.get("score",0); gr = s.get("grade","B")
                gc = grade_colors.get(gr,"#94a3b8")
                rows_html += f"""
<div style="display:flex;justify-content:space-between;align-items:center;
  padding:11px 0;border-bottom:1px solid #1a2a3a">
  <div>
    <span style="font-size:15px;font-weight:700;color:#e2e8f0">{n}</span>
    <span style="font-size:11px;color:#64748b;margin-left:6px">{c}</span>
  </div>
  <div style="text-align:right">
    <span style="font-size:14px;font-weight:600;color:#e2e8f0">{pr}원</span>
    <span style="font-size:12px;color:{chg_c};margin-left:6px">{ch}</span>
    <span style="font-size:11px;color:{gc};background:{gc}22;
      padding:2px 8px;border-radius:10px;margin-left:8px">{sc}점 {gr}</span>
  </div>
</div>"""
            st.markdown(f"""
<div style="background:#0d1520;border:1px solid #1e3a5f;border-radius:14px;
  padding:4px 16px 8px;margin-bottom:16px">
{rows_html}
</div>""", unsafe_allow_html=True)
            return  # 팝업 보여주는 동안 탭 숨김

    # 카테고리 요약 카드 (갯수 클릭 → 팝업)
    cols = st.columns(5)
    for i, (cat_name, cat_key, cat_icon) in enumerate(categories):
        cnt = len(data.get(cat_key, []))
        with cols[i]:
            st.markdown(f"""
<div style="background:linear-gradient(135deg,#0d1520,#1a2744);border:1px solid #1e3a5f;
  border-radius:12px;padding:14px 10px;text-align:center;margin-bottom:8px">
  <div style="font-size:20px">{cat_icon}</div>
  <div style="font-size:11px;color:#94a3b8;margin:4px 0">{cat_name}</div>
  <div style="font-size:26px;font-weight:900;color:#00d4ff">{cnt}</div>
</div>""", unsafe_allow_html=True)
            if st.button(f"목록 보기", key=f"popup_btn_{cat_key}"):
                st.session_state["popup_cat"] = cat_key
                st.rerun()

    tab_names = [f"{icon} {name} {len(data.get(key,[]))}" for name, key, icon in categories]
    tabs = st.tabs(tab_names)

    for idx, (tab, (cat_name, cat_key, cat_icon)) in enumerate(zip(tabs, categories)):
        with tab:
            stocks = data.get(cat_key, [])
            if not stocks:
                st.markdown('<div style="text-align:center;color:#64748b;padding:40px">데이터 없음</div>',
                            unsafe_allow_html=True)
                continue
            _render_stock_list(stocks)

def _render_stock_list(stocks):
    for i, s in enumerate(stocks):
        name  = s.get("name","")
        code  = s.get("code","")
        price = s.get("price","")
        chg   = s.get("change","")
        up    = s.get("up", True)
        score = s.get("score", 0)
        grade = s.get("grade","B")
        rsi   = s.get("rsiApprox", 50) or 50
        buy   = s.get("buy","")
        tgt   = s.get("target","")
        stop  = s.get("stop","")
        rr    = s.get("rr","")
        mkt   = s.get("mkt","").upper()
        vol   = s.get("vol", 0)
        reasons = s.get("reasons", [])

        chg_color = "#ff3b5c" if up else "#4fa3e0"
        grade_colors = {"S":"#ff3b5c","A":"#ff9900","B":"#ffc800","C":"#94a3b8"}
        grade_color = grade_colors.get(grade,"#94a3b8")

        # reasons 분류
        tech_items, basic_text, ext_text = [], "", ""
        for r in reasons:
            txt = r.get("text","") if isinstance(r,dict) else str(r)
            if "[기본적 분석]" in txt:
                basic_text = txt.replace("[기본적 분석] ","")
            elif "[외부요인]" in txt:
                ext_text = txt.replace("[외부요인] ","")
            else:
                tech_items.append(txt)

        tech_html = "".join(f'<li style="margin:3px 0;color:#94a3b8">{t}</li>' for t in tech_items[:3])
        basic_html = f'<li style="margin:3px 0;color:#60a5fa">▶ [기본적 분석] {basic_text}</li>' if basic_text else ""
        ext_html   = f'<li style="margin:3px 0;color:#a78bfa">▶ [외부요인] {ext_text}</li>' if ext_text else ""
        reasons_html = f'<ul style="margin:10px 0 0;padding-left:16px;font-size:12px;line-height:1.9">{tech_html}{basic_html}{ext_html}</ul>' if (tech_html or basic_html or ext_html) else ""

        # 거래대금 배지
        vol_str = f"{vol:,}억" if vol else ""

        st.markdown(f"""
<div class="stock-card" style="margin-bottom:16px;padding:18px 20px;">
  <!-- 상단: 종목명 + K점수 + 가격 -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
    <div>
      <span style="font-size:17px;font-weight:800;color:#e2e8f0">{name}</span>
      <span style="font-size:11px;color:#64748b;margin-left:8px">{code}</span>
      <span style="font-size:10px;color:#475569;background:#1e2a3a;padding:2px 7px;border-radius:4px;margin-left:6px">{mkt}</span>
    </div>
    <div style="text-align:right">
      <span style="font-size:13px;font-weight:700;color:{grade_color};background:{grade_color}22;padding:3px 10px;border-radius:20px">{score}점 {grade}</span>
    </div>
  </div>
  <!-- 가격 -->
  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px">
    <span style="font-size:28px;font-weight:900;color:#e2e8f0">{price}원</span>
    <span style="font-size:15px;font-weight:700;color:{chg_color}">{chg}</span>
  </div>
  <!-- 매입/목표/손절 -->
  <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
    <span style="font-size:13px;color:#64748b">매입가 <b style="color:#e2e8f0">{buy}원</b></span>
    <span style="color:#334155">·</span>
    <span style="font-size:13px;color:#64748b">목표가 <b style="color:#ff3b5c">{tgt}원</b></span>
    <span style="color:#334155">·</span>
    <span style="font-size:13px;color:#64748b">손절가 <b style="color:#4fa3e0">{stop}원</b></span>
    <span style="color:#334155">·</span>
    <span style="font-size:13px;color:#64748b">손익비 <b style="color:#e2e8f0">{rr}</b></span>
  </div>
  <!-- 배지 -->
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
    <span style="font-size:11px;background:#0f4c35;color:#00ff88;padding:3px 10px;border-radius:12px">{mkt}</span>
    <span style="font-size:11px;background:#1a2744;color:#60a5fa;padding:3px 10px;border-radius:12px">RR {rr}</span>
    {"" if not vol_str else f'<span style="font-size:11px;background:#2a1f0a;color:#fb923c;padding:3px 10px;border-radius:12px">거래대금 {vol_str}</span>'}
    <span style="font-size:11px;background:#1a2744;color:#94a3b8;padding:3px 10px;border-radius:12px">RSI {rsi:.0f}</span>
  </div>
  <!-- K 분석 사유 -->
  {f'<div style="font-size:12px;color:#64748b;margin-bottom:4px;font-weight:600">K 분석 사유</div>{reasons_html}' if reasons_html else ""}
</div>
""", unsafe_allow_html=True)

# ── 관리자 뷰 (app.py에서 import해서 사용) ─────────────────────
def admin_panel():
    """app.py 관리자 탭에서 호출"""
    st.subheader("👥 회원 관리")
    if not SUPABASE_URL:
        st.error("SUPABASE_URL / SUPABASE_SERVICE_KEY 설정 필요")
        return

    # 관리자 비번 확인
    if not st.session_state.get("admin_auth"):
        pw = st.text_input("관리자 비밀번호", type="password", key="admin_pw_input")
        if st.button("확인", key="admin_pw_btn"):
            if pw == "4545":
                st.session_state["admin_auth"] = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다")
        return

    tab_users, tab_coupons, tab_payments, tab_vip = st.tabs(["회원목록", "쿠폰발급", "결제내역", "VIP텔레그램"])

    with tab_users:
        import pandas as pd
        rows = _sb("get", "users", params={"select":"id,email,name,provider,created_at,last_login","order":"created_at.desc","limit":"100"}) or []
        subs = _sb("get", "subscriptions", params={"select":"user_id,starts_at,expires_at,status","order":"expires_at.desc","limit":"500"}) or []
        sub_map = {}
        for s in subs:
            uid = s["user_id"]
            if uid not in sub_map:
                sub_map[uid] = s

        now = datetime.now(timezone.utc)
        table = []
        for u in rows:
            s = sub_map.get(u["id"], {})
            exp_str = s.get("expires_at","")[:10] if s else ""
            start_str = s.get("starts_at","")[:10] if s else ""
            active = False
            if exp_str:
                try:
                    active = datetime.fromisoformat(s["expires_at"].replace("Z","+00:00")) > now
                except: pass
            table.append({
                "이름": u.get("name",""),
                "이메일": u.get("email",""),
                "가입방법": u.get("provider",""),
                "서비스시작": start_str,
                "서비스종료": exp_str,
                "상태": "✅활성" if active else ("⏰만료" if exp_str else "❌없음"),
                "최근접속": (u.get("last_login","") or "")[:16].replace("T"," "),
                "_id": u["id"],
            })

        if table:
            import io
            df = pd.DataFrame(table)
            display_df = df.drop(columns=["_id"])
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            st.caption(f"총 {len(df)}명")

            # 엑셀 내보내기
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                display_df.to_excel(writer, index=False, sheet_name="회원목록")
            st.download_button(
                "📥 엑셀로 저장",
                data=buf.getvalue(),
                file_name=f"kalpha_members_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_members_excel",
            )

            st.markdown("---")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**만료 2일 전 알림 발송**")
                if st.button("📢 만료임박 알림 발송", key="btn_notify_expiry"):
                    sb_check_expiry_notify()
                    st.success("알림 발송 완료")
            with col_b:
                st.markdown("**회원 삭제 (주의)**")
                del_pw   = st.text_input("삭제 확인 비번", type="password", key="del_pw")
                del_email = st.text_input("삭제할 이메일", key="del_email")
                if st.button("🗑️ 회원 삭제", key="btn_del_user", type="primary"):
                    if del_pw != "4545":
                        st.error("비번 오류")
                    elif not del_email.strip():
                        st.error("이메일 미입력")
                    else:
                        target = [r for r in table if r["이메일"] == del_email.strip()]
                        if not target:
                            st.error("해당 이메일 회원 없음")
                        else:
                            uid = target[0]["_id"]
                            # ON DELETE CASCADE로 subscriptions/payments/tg_join_requests 자동 삭제
                            result = _sb("delete", "users", params={"id": f"eq.{uid}"})
                            if result is not None:
                                st.success(f"✅ {del_email} 삭제 완료")
                                st.rerun()
                            else:
                                st.error("삭제 실패 — Supabase 오류")
        else:
            st.info("회원이 없습니다")

    with tab_coupons:
        st.markdown("**신규 쿠폰 발급**")
        c1, c2, c3 = st.columns(3)
        with c1:
            coupon_code = st.text_input("쿠폰 코드", placeholder="자동생성 or 직접입력")
        with c2:
            coupon_days = st.number_input("사용 기간(일)", min_value=1, max_value=365, value=7)
        with c3:
            coupon_uses = st.number_input("최대 사용 횟수", min_value=1, max_value=100, value=1)
        coupon_note = st.text_input("메모 (선택)")

        if st.button("쿠폰 발급", type="primary", key="btn_issue_coupon"):
            code = coupon_code.upper() if coupon_code else f"KALPHA-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
            res = _sb("post", "coupons", body={
                "code": code, "duration_days": coupon_days,
                "max_uses": coupon_uses, "note": coupon_note,
            })
            if res:
                st.success(f"✅ 쿠폰 발급 완료: **{code}** ({coupon_days}일)")
            else:
                st.error("발급 실패 (중복 코드일 수 있습니다)")

        st.markdown("---")
        st.markdown("**발급된 쿠폰 목록**")
        crows = _sb("get", "coupons", params={"order":"created_at.desc","limit":"200"})
        if crows:
            import pandas as pd, io
            df_c = pd.DataFrame(crows)[["code","duration_days","max_uses","use_count","created_at","note"]]
            df_c.columns = ["쿠폰코드","기간(일)","최대사용","사용횟수","발급일","메모"]
            df_c["발급일"] = pd.to_datetime(df_c["발급일"]).dt.strftime("%Y-%m-%d")
            st.dataframe(df_c, use_container_width=True, hide_index=True)
            buf_c = io.BytesIO()
            with pd.ExcelWriter(buf_c, engine="openpyxl") as w:
                df_c.to_excel(w, index=False, sheet_name="쿠폰목록")
            st.download_button("📥 쿠폰 엑셀 저장", data=buf_c.getvalue(),
                file_name=f"kalpha_coupons_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_coupons_excel")

    with tab_payments:
        prows = _sb("get", "payments", params={"order":"created_at.desc","limit":"100",
                    "select":"order_id,amount,plan,status,paid_at,user_id"})
        if prows:
            import pandas as pd, io
            df_p = pd.DataFrame(prows)[["order_id","amount","plan","status","paid_at"]]
            df_p.columns = ["주문번호","금액","플랜","상태","결제일"]
            df_p["금액"] = df_p["금액"].apply(lambda x: f"{x:,}원" if x else "")
            df_p["결제일"] = pd.to_datetime(df_p["결제일"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(df_p, use_container_width=True, hide_index=True)
            done = df_p[df_p["상태"]=="done"]
            st.caption(f"완료 {len(done)}건")
            buf_p = io.BytesIO()
            with pd.ExcelWriter(buf_p, engine="openpyxl") as w:
                df_p.to_excel(w, index=False, sheet_name="결제내역")
            st.download_button("📥 결제내역 엑셀 저장", data=buf_p.getvalue(),
                file_name=f"kalpha_payments_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_payments_excel")
        else:
            st.info("결제 내역이 없습니다")

    with tab_vip:
        st.markdown("**VIP 텔레그램 참가 신청 목록**")
        vrows = _sb("get", "tg_join_requests", params={
            "select": "id,user_id,status,requested_at",
            "order": "requested_at.desc", "limit": "100"
        })
        if not vrows:
            st.info("신청 내역이 없습니다")
        else:
            import pandas as pd
            # 유저 이메일 조회
            user_ids = [r["user_id"] for r in vrows]
            urows = _sb("get", "users", params={"select": "id,email,name", "limit": "200"}) or []
            uid_map = {u["id"]: u for u in urows}

            for r in vrows:
                u = uid_map.get(r["user_id"], {})
                email = u.get("email", r["user_id"][:8])
                name  = u.get("name", "")
                status = r.get("status", "pending")
                req_at = r.get("requested_at", "")[:16].replace("T", " ")
                status_badge = "✅ 승인됨" if status == "approved" else "⏳ 대기중"

                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**{name}** `{email}`  \n신청: {req_at}")
                with col2:
                    st.markdown(status_badge)
                with col3:
                    if status == "pending":
                        if st.button("✅ 승인", key=f"vip_approve_{r['id']}"):
                            _sb("patch", f"tg_join_requests?id=eq.{r['id']}", body={
                                "status": "approved",
                                "approved_at": datetime.now(timezone.utc).isoformat()
                            })
                            send_tg_admin(
                                f"✅ <b>VIP 텔레그램 승인 완료</b>\n"
                                f"👤 {name} ({email})\n"
                                f"🎉 VIP 방에 초대해주세요!"
                            )
                            st.success(f"{email} 승인 완료")
                            st.rerun()
                    else:
                        if st.button("❌ 취소", key=f"vip_revoke_{r['id']}"):
                            _sb("patch", f"tg_join_requests?id=eq.{r['id']}", body={"status": "pending"})
                            st.rerun()
                st.divider()

# ── 메인 실행 ──────────────────────────────────────────────────
inject_css()

qp = st.query_params

# OAuth 상태값 초기화
if "oauth_state" not in st.session_state:
    st.session_state["oauth_state"] = secrets.token_hex(16)

# ── OAuth 콜백 처리 ──
provider = qp.get("oauth")
code     = qp.get("code")

if provider and code:
    with st.spinner("로그인 처리 중..."):
        user_info = None
        try:
            if provider == "google":
                user_info = exchange_google(code)
            elif provider == "kakao":
                user_info = exchange_kakao(code)
            elif provider == "naver":
                user_info = exchange_naver(code, qp.get("state",""))
        except Exception as e:
            st.error(f"로그인 오류: {e}")

        if user_info and user_info.get("email"):
            uid = sb_upsert_user(
                user_info["email"], user_info["name"],
                provider, user_info["provider_id"], user_info.get("avatar","")
            )
            if uid:
                st.session_state["user"] = {"id": uid, **user_info}
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"계정 생성 실패. URL={SUPABASE_URL[:30] if SUPABASE_URL else '없음'} KEY={'있음' if SUPABASE_KEY else '없음'}")
        else:
            st.error("소셜 계정 정보를 가져올 수 없습니다.")

# ── 결제 콜백 처리 ──
elif qp.get("pay_ok") == "1":
    payment_key = qp.get("paymentKey","")
    order_id    = qp.get("orderId","")
    amount      = int(qp.get("amount", 0))
    plan        = qp.get("plan","monthly")

    user = st.session_state.get("user")
    if user and payment_key and order_id and amount:
        with st.spinner("결제 확인 중..."):
            result = toss_confirm(payment_key, order_id, amount)
            if result.get("status") == "DONE":
                sb_save_payment(user["id"], order_id, amount, plan, payment_key, "done", result)
                days = 30 if plan == "monthly" else 365
                sb_create_sub(user["id"], plan, days)
                st.session_state["sub"] = sb_get_active_sub(user["id"])
                st.query_params.clear()
                st.success("✅ 결제 완료! 서비스를 이용하실 수 있습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"결제 확인 실패: {result.get('message','알 수 없는 오류')}")
                st.query_params.clear()
    else:
        st.query_params.clear()
        st.rerun()

elif qp.get("pay_fail") == "1":
    st.error("결제가 취소되었습니다.")
    st.query_params.clear()

# ── 정상 플로우 ──
else:
    user  = st.session_state.get("user")
    sub   = st.session_state.get("sub")
    legal = st.session_state.get("legal")

    if not user:
        page_login()
    else:
        # 구독 조회 (캐시)
        if sub is None:
            sub = sb_get_active_sub(user["id"])
            st.session_state["sub"] = sub

        if not sub:
            page_subscribe(user)
        else:
            # 만료 체크
            try:
                exp_dt = datetime.fromisoformat(sub["expires_at"].replace("Z","+00:00"))
                if exp_dt < datetime.now(timezone.utc):
                    st.session_state.pop("sub", None)
                    st.warning("구독이 만료되었습니다. 다시 구독해주세요.")
                    page_subscribe(user)
                    st.stop()
            except: pass

            # 법적 동의 확인
            if legal is None:
                legal = sb_check_legal(user["id"])
                st.session_state["legal"] = legal

            if not legal:
                page_legal(user)
            else:
                page_main(user, sub)
