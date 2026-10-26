"""`cplat feedback`: a redacted, diagnostic issue draft that is only sent on --submit."""
import pytest

import core
import feedback


@pytest.mark.parametrize("raw,gone", [
    ("token gh" "p_abcdefghijklmnopqrstuvwxyz0123456789", "gh" "p_abcdefghijklmnopqrstuvwxyz0123456789"),
    ("using github" "_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz", "github" "_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz"),
    ("Authorization: Bearer eyJh" "bGciOiJIUzI1NiJ9.payload.sig", "eyJh" "bGciOiJIUzI1NiJ9"),
    ("DATABASE_PASSWORD=hunter2", "hunter2"),
    ('api_key: "sk_" "live_123456"', "sk_" "live_123456"),
    ("mail me at someone@example.com", "someone@example.com"),
    ("opened /Users/" "eike/Dev/secret-project/file.py", "eike"),
    ("key AKIA" "ABCDEFGHIJKLMNOP", "AKIA" "ABCDEFGHIJKLMNOP"),
    ("blob QWxhZGRp" "bjpvcGVuIHNlc2FtZVF1ZXJ5U3RyaW5nVmFsdWU0NTY3ODkw", "QWxhZGRp" "bjpvcGVuIHNlc2FtZVF1ZXJ5U3RyaW5nVmFsdWU0NTY3ODkw"),
])
def test_secrets_and_personal_data_are_removed(raw, gone):
    assert gone not in feedback.redact(raw)


def test_useful_context_survives_redaction():
    text = "commit 0123456789abcdef0123456789abcdef01234567 failed in scripts/render.py line 42: service 'todo-api' missing"
    assert feedback.redact(text) == text


def test_draft_contains_versions_command_and_trimmed_output(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(feedback, "plugin_versions", lambda: {"shared": "0.7.0"})
    log = tmp_path / "err.txt"
    log.write_text("\n".join(f"line {i}" for i in range(500)) + "\nTOKEN=abc123secret\n")
    rc = feedback.main(["--title", "render fails", "--what", "I ran compose and it crashed", "--command", "/gitops:compose add todo-api",
                        "--details-file", str(log), "--repo-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"platform: {core.platform_version()}" in out and "shared 0.7.0" in out
    assert "/gitops:compose add todo-api" in out and "I ran compose and it crashed" in out
    assert "abc123secret" not in out and "line 0\n" not in out and "line 499" in out   # secret gone, only the tail kept
    assert "Nothing was sent" in out


def test_nothing_is_filed_without_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "create_issue", lambda *a: pytest.fail("must not file without --submit"))
    assert feedback.main(["--title", "x", "--repo-dir", str(tmp_path)]) == 0


def test_submit_files_with_labels(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "has_gh", lambda: True)
    seen = {}
    monkeypatch.setattr(feedback, "create_issue", lambda title, body, labels: seen.update(title=title, body=body, labels=labels) or "https://github.com/x/y/issues/1")
    assert feedback.main(["--kind", "idea", "--title", "support cockroach", "--what", "please", "--submit", "--repo-dir", str(tmp_path)]) == 0
    assert seen["labels"] == ["feedback", "enhancement"] and "## The idea" in seen["body"]
    assert "Filed: https://github.com/x/y/issues/1" in capsys.readouterr().out


def test_without_gh_a_prefilled_browser_link_is_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "has_gh", lambda: False)
    monkeypatch.setattr(feedback, "create_issue", lambda *a: pytest.fail("no gh available"))
    feedback.main(["--title", "needs a link", "--what", "gh" "p_abcdefghijklmnopqrstuvwxyz0123456789", "--submit", "--repo-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "https://github.com/ika100/sdlc-foundry/issues/new?title=needs%20a%20link" in out
    assert "gh" "p_abcdefghij" not in out


def test_an_unexpected_crash_points_to_the_report_command(monkeypatch, capsys):
    import cplat
    import status
    monkeypatch.setattr(status, "main", lambda argv: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cplat.main(["system", "status"]) == 70
    err = capsys.readouterr().err
    assert "unexpected failure" in err and "/issue:report" in err
