"""A remote command followed by redirections is still opened and split (2026-11-12: two false destructive stops)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import default_rules as d  # noqa: E402

SSH = ("timeout 600 ssh box 'rm -rf /tmp/ms-audit && sudo -u ship git -C /home/ship/site bundle create /home/ship/ms.bundle HEAD"
       " >/dev/null 2>&1; cd /tmp/ms-audit' < /dev/null")


def test_redirected_ssh_is_split():
    segs = [s for s, _ in d._expanded(SSH)]
    assert any(s.startswith("rm -rf /tmp/ms-audit") and "/home/ship/site" not in s for s in segs), segs


def test_temp_folder_delete_inside_ssh_is_not_a_stop():
    hits = d.check_command(SSH, cwd="/tmp", probes={}, ok=None)
    assert not any("/home/ship/site" in str(h) for h in hits), hits


def test_real_wipe_inside_redirected_ssh_still_stops():
    hits = d.check_command("ssh box 'rm -rf ~' < /dev/null", cwd="/tmp", probes={}, ok=None)
    assert hits, "a home wipe through ssh must still stop"
