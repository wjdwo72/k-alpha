-- K-ALPHA 유저 서비스 Supabase 스키마
-- Supabase > SQL Editor 에서 전체 실행

-- 1. 유저 테이블
CREATE TABLE IF NOT EXISTS users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT UNIQUE NOT NULL,
    name         TEXT,
    avatar_url   TEXT,
    provider     TEXT NOT NULL,   -- 'google' | 'kakao' | 'naver' | 'email'
    provider_id  TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    last_login   TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 구독 테이블
CREATE TABLE IF NOT EXISTS subscriptions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan        TEXT NOT NULL,   -- 'monthly' | 'yearly' | 'coupon'
    status      TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'expired' | 'cancelled'
    starts_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_sub_status ON subscriptions(status, expires_at);

-- 3. 쿠폰 테이블
CREATE TABLE IF NOT EXISTS coupons (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code          TEXT UNIQUE NOT NULL,
    duration_days INTEGER NOT NULL DEFAULT 7,
    max_uses      INTEGER NOT NULL DEFAULT 1,
    use_count     INTEGER NOT NULL DEFAULT 0,
    used_by       UUID REFERENCES users(id),
    used_at       TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,          -- 쿠폰 자체 만료일 (NULL=무제한)
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    note          TEXT                  -- 관리자 메모
);

-- 4. 결제 테이블
CREATE TABLE IF NOT EXISTS payments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id     TEXT UNIQUE NOT NULL,  -- 토스 orderId
    payment_key  TEXT,                  -- 토스 paymentKey (승인 후)
    amount       INTEGER NOT NULL,
    plan         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'done'|'failed'|'cancelled'
    paid_at      TIMESTAMPTZ,
    raw          JSONB,                 -- 토스 응답 원본
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_pay_order ON payments(order_id);

-- 5. 법적 동의 테이블
CREATE TABLE IF NOT EXISTS legal_agreements (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version    TEXT NOT NULL DEFAULT 'v1',
    agreed_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_legal_user_ver ON legal_agreements(user_id, version);

-- ── RLS (Row Level Security) 설정 ────────────────────────────
ALTER TABLE users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE coupons         ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments        ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_agreements ENABLE ROW LEVEL SECURITY;

-- service_role (백엔드) 전체 접근 허용
CREATE POLICY "service_role_all_users"           ON users            FOR ALL USING (true);
CREATE POLICY "service_role_all_subs"            ON subscriptions    FOR ALL USING (true);
CREATE POLICY "service_role_all_coupons"         ON coupons          FOR ALL USING (true);
CREATE POLICY "service_role_all_payments"        ON payments         FOR ALL USING (true);
CREATE POLICY "service_role_all_legal"           ON legal_agreements FOR ALL USING (true);

-- ── 관리자용 편의 뷰 ─────────────────────────────────────────
CREATE OR REPLACE VIEW admin_users_view AS
SELECT
    u.id,
    u.email,
    u.name,
    u.provider,
    u.created_at,
    u.last_login,
    s.plan,
    s.status        AS sub_status,
    s.expires_at,
    p.amount        AS last_payment,
    p.paid_at       AS last_paid_at
FROM users u
LEFT JOIN LATERAL (
    SELECT * FROM subscriptions
    WHERE user_id = u.id AND status = 'active'
    ORDER BY expires_at DESC LIMIT 1
) s ON true
LEFT JOIN LATERAL (
    SELECT * FROM payments
    WHERE user_id = u.id AND status = 'done'
    ORDER BY paid_at DESC LIMIT 1
) p ON true
ORDER BY u.created_at DESC;
