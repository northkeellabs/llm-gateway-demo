#!/usr/bin/env bash
# Native (no Docker) install on Ubuntu 22.04/24.04. Run as root from the repo root: sudo deploy/install.sh
set -euo pipefail
LITELLM_VERSION="1.109.1"
APP=/opt/llm-gateway
SRC="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update
apt-get install -y postgresql python3 python3-venv python3-pip curl openssl
systemctl enable --now postgresql

id litellm >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin litellm
mkdir -p "$APP"; cp "$SRC/config.yaml" "$APP/"

# Secrets: generated once, never overwritten.
if [ ! -f "$APP/.env" ]; then
  DBPW=$(openssl rand -hex 16)
  sudo -u postgres psql -c "CREATE USER litellm WITH PASSWORD '$DBPW'" -c "CREATE DATABASE litellm OWNER litellm"
  cat > "$APP/.env" <<ENV
LITELLM_MASTER_KEY=sk-$(openssl rand -hex 24)
LITELLM_SALT_KEY=sk-salt-$(openssl rand -hex 24)
DATABASE_URL=postgresql://litellm:$DBPW@127.0.0.1:5432/litellm
UI_USERNAME=admin
UI_PASSWORD=$(openssl rand -hex 12)
STORE_MODEL_IN_DB=False
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
ENV
fi

python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --upgrade pip
"$APP/.venv/bin/pip" install "litellm[proxy]==$LITELLM_VERSION" prisma

chown -R litellm:litellm "$APP"; chmod 600 "$APP/.env"

# Prisma client + DB schema: generate the client, then LiteLLM runs `prisma migrate deploy` on first start.
# (Prisma downloads its engine binaries from binaries.prisma.sh here: the server needs outbound HTTPS.)
set -a; . "$APP/.env"; set +a
sudo -u litellm env PATH="$APP/.venv/bin:$PATH" HOME="$APP" \
  prisma generate --schema "$APP/.venv/lib/"python3*/site-packages/litellm/proxy/schema.prisma

cp "$SRC/deploy/litellm.service" /etc/systemd/system/litellm.service
systemctl daemon-reload
systemctl enable --now litellm
echo "Done. Credentials are in $APP/.env. Check: curl http://127.0.0.1:4000/health/liveliness"
