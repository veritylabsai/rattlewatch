#!/usr/bin/env bash
# Set (or rotate) the /admin/ Basic-auth password.
#
# The plaintext password is read from STDIN, never from an argument, so it does
# not land in shell history or in `ps` output. It is hashed with bcrypt and only
# the hash is written to disk.
#
#   printf '%s' 'the-password' | ./set-password.sh
#   ./set-password.sh            # prompts, no echo
set -euo pipefail

HTPASSWD=/etc/nginx/rattlewatch.htpasswd
USERNAME="${RATTLEWATCH_ADMIN_USER:-admin}"

if [ -t 0 ]; then
  read -r -s -p "New password for '${USERNAME}': " PW; echo
  read -r -s -p "Repeat: " PW2; echo
  [ "${PW}" = "${PW2}" ] || { echo "passwords do not match" >&2; exit 1; }
else
  PW="$(cat)"
fi

if [ "${#PW}" -lt 20 ]; then
  echo "refusing: password must be at least 20 characters" >&2
  exit 1
fi

# bcrypt via the system python3-bcrypt package. nginx verifies the hash through
# crypt(3), which supports the $2b$ format on this platform.
HASH="$(printf '%s' "${PW}" | python3 -c '
import sys, bcrypt
pw = sys.stdin.buffer.read()
sys.stdout.write(bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode())
')"

umask 077
TMP="$(mktemp)"
printf '%s:%s\n' "${USERNAME}" "${HASH}" > "${TMP}"
sudo install -o root -g www-data -m 0640 "${TMP}" "${HTPASSWD}"
rm -f "${TMP}"

echo "wrote ${HTPASSWD} for user '${USERNAME}'"
sudo ls -la "${HTPASSWD}"
