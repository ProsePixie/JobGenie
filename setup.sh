#!/usr/bin/env bash
# First-run helper for macOS, Linux and WSL.
#
# 1. If profile/ does not exist, copies the fictional example (profile.example/)
#    to profile/ so the app can be tried. An existing profile/ is never touched.
# 2. Runs tools/doctor.py, which checks Python, Chrome/Edge, poppler and the
#    Claude Code CLI and says how to fix anything missing. It installs nothing.
#
# It does not install packages and does not start the app. It exits non-zero
# when the doctor finds a required tool missing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -d "profile.example" ]; then
    echo "profile.example/ is missing from $ROOT. Is this a complete JobGenie checkout?" >&2
    exit 1
fi

echo "== Profile =="
if [ -e "profile" ]; then
    echo "profile/ already exists and was left exactly as it is."
else
    cp -R "profile.example" "profile"
    echo "Copied the fictional example (Jane Doe) to profile/, so you can try the app."
    echo "When you are ready to use your own data, see step 3 below."
fi
echo

echo "== Checking your tools =="
status=0
python3 tools/doctor.py || status=$?
echo

cat <<'EOF'
== Next steps ==
1. Fix anything the check above marked MISSING (Chrome, pdftotext, Python).
2. Try the app:            python3 web/server.py
3. Use your own CV:        put it (PDF or DOCX) in inbox/, open this folder in
                           Claude Code and type /setup. To start from a blank
                           profile instead of Jane Doe, rename or remove profile/
                           first, then run: python3 tools/new_profile.py
Full guide: docs/SETUP.md
EOF
exit "$status"
