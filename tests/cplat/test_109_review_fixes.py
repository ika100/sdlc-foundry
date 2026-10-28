"""Review fixes of spec 109: a failed remote read is never "absent" (AC-109.9), an unreadable verification.md never ends the
run (AC-109.11). Fixture repos use the scratch spec 901."""
from chain_support import APP_SLUG, BRANCH, ENVS, FakeGh, build_gitops, build_world, chain, chain_text, links, pr_entry, rendered


class FlakyRawGh(FakeGh):
    """Serves the gitops-app, but every raw file read answers `raw_answer` (rc, stderr); optionally only for some paths."""

    def __init__(self, raw_answer, only=None, **kw):
        super().__init__(**kw)
        self.raw_answer, self.only = raw_answer, only

    def _api(self, args):
        if any("raw" in a for a in args) and (self.only is None or any(self.only in a for a in args)):
            rc, err = self.raw_answer
            return rc, "", err
        return super()._api(args)


def _setup(tmp_path, monkeypatch, raw_answer, only=None, pins=None):
    w = build_world(tmp_path)
    g = build_gitops(w, pins or {"dev": "v1.2.0", "staging": "v1.2.0", "prod": "v1.2.0"},
                      name="served-only")   # not the sibling clone layout, so no local fallback
    FlakyRawGh(raw_answer, only=only, issues={164: "CLOSED"}, prs={BRANCH: [pr_entry(301, w.shas["m"])]},
               repos={APP_SLUG: g}).install(monkeypatch)
    return w


def _assert_unknown_envs(capsys, w):
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    ls = links(doc, "AC-901.1")
    for e in ENVS:
        text = rendered(ls[f"env {e}"])
        assert text.startswith("unknown: ") and f"gitops-app {APP_SLUG} not reachable" in text, text
    assert APP_SLUG in doc["note"]
    _, out, _ = chain_text(capsys, w.root)
    assert not [ln for ln in out.splitlines() if ln.strip().startswith("env ") and " missing: " in ln]
    assert "not deployed" not in out and "is not a component" not in out


def test_timed_out_gitops_reads_make_the_environments_unknown_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = _setup(tmp_path, monkeypatch, (124, "timed out"))
    _assert_unknown_envs(capsys, w)


def test_server_errors_on_gitops_reads_make_the_environments_unknown_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = _setup(tmp_path, monkeypatch, (1, "gh: Service Unavailable (HTTP 503)"))
    _assert_unknown_envs(capsys, w)


def test_forbidden_gitops_reads_make_the_environments_unknown_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = _setup(tmp_path, monkeypatch, (1, "gh: Resource not accessible (HTTP 403)"))
    _assert_unknown_envs(capsys, w)


def test_a_404_for_an_absent_overlay_is_still_not_deployed_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = _setup(tmp_path, monkeypatch, (1, "gh: Not Found (HTTP 404)"), only="overlays/prod",
               pins={"dev": "v1.2.0", "staging": "v1.2.0", "prod": "v1.2.0"})
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    ls = links(doc, "AC-901.1")
    assert rendered(ls["env prod"]) == "n/a: not deployed to prod"
    assert ls["env dev"]["state"] == "ok"
    assert doc["note"] is None


def test_an_unreadable_verification_file_is_an_unknown_link_and_exit_0_ac_109_11(tmp_path, capsys, monkeypatch):  # AC-109.11
    w = build_world(tmp_path)
    FakeGh(issues={164: "CLOSED"}, prs={BRANCH: [pr_entry(301, w.shas["m"])]}).install(monkeypatch)
    (w.spec_dir / "verification.md").write_bytes(b"# Verification\n\n**Result:** pass \xff\xfe\n")
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    assert rendered(links(doc, "AC-901.1")["verdict"]).startswith("unknown: UnicodeDecodeError")
    rc, out, _ = chain_text(capsys, w.root)
    assert rc == 0 and "chain: " in out
