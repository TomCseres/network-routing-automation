#!/bin/sh
# ============================================================
# Alpine bootstrap for network-routing-automation
#
# Paste into Alpine console at the start of each lab session.
# Edit the CONFIG block once with your details and PAT.
# ============================================================

set -e

# ====== CONFIG (edit these once) ======
GITHUB_USER=""
GITHUB_TOKEN="ghp_PASTE_YOUR_TOKEN_HERE"
GIT_USER_NAME=""
GIT_USER_EMAIL="your-github-email@example.com"
REPO_NAME="network-routing-automation"
# =======================================

WORKDIR="/root/${REPO_NAME}"
REPO_URL="https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"

echo "==> [1/7] Installing system packages..."
apk update -q
apk add -q python3 py3-pip openssh-client git

echo "==> [2/7] Configuring git identity..."
git config --global user.name  "${GIT_USER_NAME}"
git config --global user.email "${GIT_USER_EMAIL}"
git config --global init.defaultBranch main

echo "==> [3/7] Cloning or updating repo..."
if [ ! -d "${WORKDIR}" ]; then
    git clone -q "${REPO_URL}" "${WORKDIR}"
    echo "    cloned fresh."
else
    cd "${WORKDIR}"
    git pull -q
    echo "    pulled latest."
fi

cd "${WORKDIR}"

echo "==> [4/7] Ensuring .gitignore exists..."
if [ ! -f .gitignore ]; then
    cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
EOF
    echo "    created."
else
    echo "    already present."
fi

echo "==> [5/7] Setting up Python venv..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
. .venv/bin/activate

echo "==> [6/7] Installing Python dependencies..."
# Note: 'genie' (Cisco pyATS) is intentionally NOT installed - it ships
# only as glibc wheels and is incompatible with Alpine's musl libc.
# All scripts use plain netmiko + substring matching, which is enough.
if [ -f requirements.txt ]; then
    pip install -q -r requirements.txt
else
    pip install -q netmiko jinja2 pyyaml
    pip freeze > requirements.txt
fi

echo "==> [7/7] Pre-accepting SSH host keys for Cisco devices..."
mkdir -p ~/.ssh
for ip in 192.168.255.10 192.168.255.11 192.168.255.12 192.168.255.13; do
    ssh-keyscan -H -t rsa "${ip}" >> ~/.ssh/known_hosts 2>/dev/null || true
done

echo ""
echo "==> Quick reachability check..."
for ip in 192.168.255.10 192.168.255.11 192.168.255.12 192.168.255.13; do
    if ping -c 1 -W 2 "${ip}" >/dev/null 2>&1; then
        echo "    ${ip}  reachable"
    else
        echo "    ${ip}  UNREACHABLE"
    fi
done

echo ""
echo "============================================================"
echo "  Setup complete."
echo "  Working dir: ${WORKDIR}"
echo "  Venv active in THIS shell (if you sourced the script)."
echo ""
echo "  To enter the project shell from a new terminal:"
echo "    cd ${WORKDIR} && . .venv/bin/activate"
echo ""
echo "  SSH to a router (password cisco123):"
echo "    ssh admin@192.168.255.10"
echo "============================================================"
