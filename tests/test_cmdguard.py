import cmdguard


def _home(tmp_path, paid="", hosts=""):
    if paid:
        (tmp_path / "paid_patterns.txt").write_text(paid, encoding="utf-8")
    if hosts:
        (tmp_path / "box_hosts.txt").write_text(hosts, encoding="utf-8")
    return str(tmp_path)


PAID = "queue\\.fal\\.run\n\\bmodal\\s+run\\b\nhttps?://[^\\s'\"]*/(generate|render)\\b\n"


def test_no_list_no_money_guard(tmp_path):
    assert cmdguard.money_guard("modal run x.py", "", _home(tmp_path)) == ""


def test_paid_run_needs_the_owners_yes_and_a_retry_does_not_pass(tmp_path):
    h = _home(tmp_path, PAID)
    assert "PAID RUN" in cmdguard.money_guard("modal run tests/x.py", "check the disk", h)
    assert "PAID RUN" in cmdguard.money_guard("modal run tests/x.py", "check the disk", h)
    assert cmdguard.money_guard("modal run tests/x.py", "yes, do it", h) == ""


def test_reading_or_searching_a_paid_name_is_not_a_paid_run(tmp_path):
    h = _home(tmp_path, PAID)
    assert cmdguard.money_guard('grep -n "queue.fal.run\\|fal-ai/" a.py', "", h) == ""
    assert cmdguard.money_guard("cd /data && cat notes.md | grep render", "", h) == ""
    assert cmdguard.money_guard("ls src/render && wc -l src/render/*.js", "", h) == ""
    assert "PAID RUN" in cmdguard.money_guard("curl -s http://10.0.0.1:8796/generate -d x", "", h)


def test_flood_counter_off_without_hosts_and_on_with_them(tmp_path):
    h = _home(tmp_path)
    assert all(cmdguard.box_flood(f"ssh mybox 'x{i}'", h) == "" for i in range(10))
    h2 = _home(tmp_path, hosts="mybox*\n")
    out = [cmdguard.box_flood(f"ssh mybox-direct 'x{i}'", h2) for i in range(8)]
    assert out[:6] == [""] * 6 and "FLOOD" in out[6]
