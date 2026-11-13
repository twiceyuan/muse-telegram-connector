#!/usr/bin/env bash
# (Re)install the systemd hosting for the Telegram listener.
# Run from a Muse turn (muse.exec): it snapshots the current egress
# proxy environment into egress.env (600 perms) because that runtime
# credential rotates when the VM is replaced, and /etc/systemd/system
# does not survive a VM replacement either. The liveness-hook fallback
# (detached revival) covers the gap until this is re-run.
set -euo pipefail
DIR=/home/hatch/workspace/telegram-relay/systemd
python3 - << 'PY'
import os
keys = ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY","no_proxy","NO_PROXY"]
path = "/home/hatch/workspace/telegram-relay/systemd/egress.env"
with open(path, "w", encoding="utf-8") as fh:
    for k in keys:
        if os.environ.get(k):
            fh.write("%s=%s\n" % (k, os.environ[k]))
os.chmod(path, 0o600)
print("egress.env refreshed")
PY
cp "$DIR/tg-listener.service" /etc/systemd/system/tg-listener.service
systemctl daemon-reload
systemctl enable tg-listener.service
systemctl restart tg-listener.service
systemctl is-active tg-listener.service
