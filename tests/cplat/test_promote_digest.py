"""Spec 106 acceptance tests, prod runs the exact image staging tested (AC-106.1 .. AC-106.12).

Seams (design.md "Contract"): `registry.gh` (paged package versions), `registry.digests`, `promote.gh` (tags, as in test_gitops),
`gitops.open_pr`, `evidence.*` (the fixtures of test_staging_093_evidence). The templates' CI is read as text."""
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

import core
import gitops
import promote
import registry
from test_gitops import SHA, commit, composed, gh, gitops_repo, pin  # noqa: F401  (fixtures)
from test_staging_093_evidence import ev  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
IMAGE_TEMPLATES = ["service-python", "service-java", "service-go", "web-nextjs"]
STAGING = "sha-" + SHA
RELEASE = "1.3.0"
D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
IMAGE = "ghcr.io/acme/todo-api"


class Reg:
    """`registry.gh` replaced: the package versions of every image, served 100 per page."""

    def __init__(self):
        self.tags: dict[str, str] = {STAGING: D1, RELEASE: D1}     # tag -> digest (todo-api)
        self.extra: list[dict] = []                                  # more versions, appended
        self.calls: list[list[str]] = []
        self.fail = False

    def versions(self):
        out = [{"name": d, "metadata": {"container": {"tags": [t]}}} for t, d in self.tags.items()]
        return out + self.extra

    def __call__(self, args):
        self.calls.append(args)
        if self.fail:
            raise core.PlatformError("gh: HTTP 403: you need the read:packages scope")
        path = args[1]
        page = int(re.search(r"[?&]page=(\d+)", path).group(1)) if re.search(r"[?&]page=(\d+)", path) else 1
        assert "per_page=100" in path
        vs = self.versions()
        return json.dumps(vs[(page - 1) * 100: page * 100])


@pytest.fixture()
def reg(monkeypatch):
    fake = Reg()
    monkeypatch.setattr(registry, "gh", fake)
    return fake


@pytest.fixture()
def at_staging(gitops_repo, gh, ev, reg, capsys):  # noqa: F811
    gh.image_tags["todo-api"] |= {STAGING}
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--sha", SHA, "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    reg.calls.clear()
    capsys.readouterr()
    return gitops_repo


def attempt(argv, capsys):
    """(exit code, everything printed or raised). A refusal may raise PlatformError or return non-zero."""
    try:
        rc = promote.main(argv)
    except core.PlatformError as e:
        rc, extra = 1, f"{e}\n{e.hint or ''}"
    except SystemExit as e:
        rc, extra = (e.code or 1), ""
    else:
        extra = ""
    cap = capsys.readouterr()
    return rc, cap.out + cap.err + extra


def prod(repo, *extra):
    return ["todo-api", "--to", "prod", "--repo-dir", str(repo), *extra]


def unchanged(repo):
    return subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout.strip() == ""


def prod_untouched(repo):
    """The prod overlay holds only the template's empty .gitkeep and no commit after the template touched it (nothing promoted)."""
    prod_dir = repo / "applications/todo/overlays/prod"
    files = sorted(str(f.relative_to(prod_dir)) for f in prod_dir.rglob("*") if f.is_file()) if prod_dir.exists() else []
    touched = subprocess.run(["git", "log", "--format=%H", "--", "applications/todo/overlays/prod"], cwd=repo,
                             capture_output=True, text=True).stdout.split()
    return files in ([], [".gitkeep"]) and all((prod_dir / f).read_bytes() == b"" for f in files) and len(touched) <= 1


# ---------------- registry.digests ----------------

def test_digests_maps_every_tag_and_none_for_a_missing_one(reg):
    """AC-106.4: registry.digests answers {tag: digest|None} in one pass."""
    assert registry.digests(IMAGE, [STAGING, RELEASE, "9.9.9"]) == {STAGING: D1, RELEASE: D1, "9.9.9": None}


def test_digests_pages_until_a_short_page(reg):
    """AC-106.5: pages of 100 versions are followed (per_page=100&page=N) until a short page."""
    reg.tags = {}
    reg.extra = [{"name": f"sha256:{i:064x}", "metadata": {"container": {"tags": [f"t{i}"]}}} for i in range(250)]
    got = registry.digests(IMAGE, ["t0", "t249", "t250"])
    assert got["t0"] == f"sha256:{0:064x}" and got["t249"] == f"sha256:{249:064x}" and got["t250"] is None
    pages = [c for c in reg.calls if "/versions" in c[1]]
    assert len(pages) == 3 and all("page=" in c[1] for c in pages)


def test_digests_reads_at_most_twenty_pages(reg):
    """AC-106.5: a package with endless versions is read for 20 pages, no more."""
    reg.tags = {}
    reg.extra = [{"name": f"sha256:{i:064x}", "metadata": {"container": {"tags": [f"t{i}"]}}} for i in range(3000)]
    registry.digests(IMAGE, ["nope"])
    assert len([c for c in reg.calls if "users" in c[1]]) == 20


def test_digests_raises_registry_error_when_the_lookup_fails(reg):
    """AC-106.5: a failed lookup raises RegistryError, never an empty answer."""
    reg.fail = True
    with pytest.raises(registry.RegistryError):
        registry.digests(IMAGE, [STAGING])


# ---------------- AC-106.1 ----------------

def test_matching_digests_promote_as_before(at_staging, reg, capsys):
    """AC-106.1: both tags resolve to the same digest, the promotion proceeds (pin, [PRODUCTION])."""
    rc, out = attempt(prod(at_staging, "--dry-run"), capsys)
    assert rc == 0 and "[PRODUCTION]" in out
    assert attempt(prod(at_staging), capsys)[0] == 0
    assert pin(at_staging, "prod", "todo-api") == RELEASE
    assert any("/versions" in c[1] for c in reg.calls), "the digests were never read"


# ---------------- AC-106.2 ----------------

def test_a_digest_mismatch_refuses_and_changes_nothing(at_staging, reg, capsys):
    """AC-106.2: names service, both tags and digests, 'prod would not run what staging tested', the next step; nothing written."""
    reg.tags[RELEASE] = D2
    rc, out = attempt(prod(at_staging, "--pr"), capsys)
    assert rc != 0 and unchanged(at_staging)
    for needle in ("todo-api", STAGING, RELEASE, D1, D2, "prod would not run what staging tested", "re-publish"):
        assert needle in out, needle
    assert prod_untouched(at_staging)   # the template ships overlays/prod/.gitkeep, so check its content, not its existence


def test_a_mismatch_opens_no_pr(at_staging, reg, monkeypatch, capsys):
    """AC-106.2: no PR is opened."""
    reg.tags[RELEASE] = D2
    opened = []
    monkeypatch.setattr(gitops, "open_pr", lambda *a: opened.append(a) or "url")
    rc, _ = attempt(prod(at_staging, "--pr"), capsys)
    assert rc != 0 and opened == []


# ---------------- AC-106.3 ----------------

def test_dry_run_shows_both_digests_and_match(at_staging, capsys):
    """AC-106.3: `staging: <tag> <digest>`, `prod: <tag> <digest>` and match."""
    rc, out = attempt(prod(at_staging, "--dry-run"), capsys)
    assert rc == 0
    assert f"staging: {STAGING} {D1}" in out and f"prod: {RELEASE} {D1}" in out
    assert re.search(r"\bmatch\b", out) and "mismatch" not in out


def test_dry_run_mismatch_exits_1_and_writes_nothing(at_staging, reg, capsys):
    """AC-106.3: a mismatch in dry-run exits 1."""
    reg.tags[RELEASE] = D2
    rc, out = attempt(prod(at_staging, "--dry-run"), capsys)
    assert rc == 1 and unchanged(at_staging)
    assert f"staging: {STAGING} {D1}" in out and f"prod: {RELEASE} {D2}" in out and "mismatch" in out


def test_dry_run_json_has_the_digests_per_service(at_staging, capsys):
    """AC-106.3: data.digests[<svc>] with tags, digests and result."""
    rc, out = attempt(prod(at_staging, "--dry-run", "--json"), capsys)
    d = json.loads(out)["digests"]["todo-api"]
    assert rc == 0 and d == {"staging_tag": STAGING, "staging_digest": D1, "release_tag": RELEASE, "release_digest": D1, "result": "match"}


def test_dry_run_json_mismatch_exits_1(at_staging, reg, capsys):
    """AC-106.3: the same in JSON, with result mismatch."""
    reg.tags[RELEASE] = D2
    rc, out = attempt(prod(at_staging, "--dry-run", "--json"), capsys)
    assert rc == 1 and json.loads(out)["digests"]["todo-api"]["result"] == "mismatch"


# ---------------- AC-106.4 ----------------

def test_a_release_tag_missing_in_the_registry_is_named(at_staging, reg, capsys):
    """AC-106.4: the release tag is named as the missing one; no mismatch is claimed."""
    del reg.tags[RELEASE]
    rc, out = attempt(prod(at_staging), capsys)
    assert rc != 0 and unchanged(at_staging) and RELEASE in out and "release" in out.lower() and "would not run" not in out


def test_a_staging_tag_missing_in_the_registry_is_named(at_staging, reg, capsys):
    """AC-106.4: the staging tag is named as the missing one."""
    del reg.tags[STAGING]
    rc, out = attempt(prod(at_staging), capsys)
    assert rc != 0 and unchanged(at_staging) and STAGING in out and "staging" in out.lower() and "would not run" not in out


def test_the_existing_release_image_refusal_is_kept(at_staging, gh, capsys):  # noqa: F811
    """AC-106.4: a release without a published image still says 'does not exist'."""
    gh.image_tags["todo-api"].discard(RELEASE)
    rc, out = attempt(prod(at_staging, "--version", "v" + RELEASE), capsys)
    assert rc != 0 and "does not exist" in out


# ---------------- AC-106.5 ----------------

def test_a_failed_lookup_refuses_and_names_the_fix(at_staging, reg, capsys):
    """AC-106.5: never a match when a digest cannot be resolved; the fix (token scope) is named."""
    reg.fail = True
    rc, out = attempt(prod(at_staging), capsys)
    assert rc != 0 and unchanged(at_staging) and "read:packages" in out and "gh api" in out
    assert prod_untouched(at_staging)   # the template ships overlays/prod/.gitkeep, so check its content, not its existence


def test_a_failed_lookup_in_dry_run_is_not_a_match(at_staging, reg, capsys):
    """AC-106.5: dry-run does not print match for an unresolved digest."""
    reg.fail = True
    rc, out = attempt(prod(at_staging, "--dry-run"), capsys)
    assert rc != 0 and not re.search(r"\bmatch\b", out)


# ---------------- AC-106.6 ----------------

def test_no_verify_skips_the_digest_check_for_prod(at_staging, reg, capsys):
    """AC-106.6: no registry call, one line says the identity was not verified."""
    reg.tags[RELEASE] = D2
    reg.fail = True
    rc, out = attempt(prod(at_staging, "--no-verify"), capsys)
    assert rc == 0 and out.count("image identity not verified (--no-verify)") == 1 and reg.calls == []


def test_staging_promotion_makes_no_digest_check(gitops_repo, gh, reg, ev, capsys):  # noqa: F811
    """AC-106.6: dev to staging is unchanged, no digest lookup."""
    composed(gitops_repo, "todo-api")
    rc, out = attempt(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)], capsys)
    assert rc == 0 and reg.calls == [] and "image identity not verified" not in out


# ---------------- AC-106.7 ----------------

REASON = "The release was rebuilt on purpose."


def test_the_override_with_a_reason_proceeds_and_states_both_digests(at_staging, reg, monkeypatch, capsys):
    """AC-106.7: output and PR body say 'digest mismatch accepted: <reason>' with both digests."""
    reg.tags[RELEASE] = D2
    opened = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: opened.append(body) or "https://github.com/acme/g/pull/9")
    rc, out = attempt(prod(at_staging, "--pr", "--accept-digest-mismatch", REASON), capsys)
    assert rc == 0 and pin(at_staging, "prod", "todo-api") == RELEASE
    for text in (out, opened[0]):
        assert f"digest mismatch accepted: {REASON}" in text and D1 in text and D2 in text


@pytest.mark.parametrize("reason", ["", "ok", "no full stop here", "two words."])
def test_the_override_without_a_real_sentence_is_refused(at_staging, reg, capsys, reason):
    """AC-106.7: the reason needs at least 3 words and a closing . ! or ?."""
    reg.tags[RELEASE] = D2
    rc, out = attempt(prod(at_staging, "--accept-digest-mismatch", reason), capsys)
    assert rc != 0 and unchanged(at_staging) and "unrecognized" not in out and "reason" in out.lower()


@pytest.mark.parametrize("reason", ["Shipped on purpose!", "Is it really intended?"])
def test_the_override_accepts_other_sentence_ends(at_staging, reg, capsys, reason):
    """AC-106.7: ! and ? close a sentence too."""
    reg.tags[RELEASE] = D2
    assert attempt(prod(at_staging, "--accept-digest-mismatch", reason), capsys)[0] == 0


def test_the_override_does_not_cover_a_missing_tag(at_staging, reg, capsys):
    """AC-106.7: a missing release tag still refuses."""
    del reg.tags[RELEASE]
    rc, out = attempt(prod(at_staging, "--accept-digest-mismatch", REASON), capsys)
    assert rc != 0 and unchanged(at_staging) and "unrecognized" not in out and RELEASE in out


def test_the_override_does_not_cover_a_failed_lookup(at_staging, reg, capsys):
    """AC-106.7: a failed lookup still refuses."""
    reg.fail = True
    rc, out = attempt(prod(at_staging, "--accept-digest-mismatch", REASON), capsys)
    assert rc != 0 and unchanged(at_staging) and "unrecognized" not in out and "read:packages" in out


# ---------------- AC-106.8 ----------------

def _pin_staging(repo, tag):
    k = repo / "applications/todo/overlays/staging/todo-api/kustomization.yaml"
    doc = yaml.safe_load(k.read_text())
    doc["images"][0]["newTag"] = tag
    k.write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(repo, "repin")


@pytest.mark.parametrize("tag", ["latest", "sha-aaaaaaa", "1.2.0", "sha-" + "a" * 39])
def test_a_staging_tag_that_is_not_a_sha_build_cannot_be_identified(at_staging, reg, capsys, tag):
    """AC-106.8: 'the staging image cannot be identified: <tag>', even when the registry knows that tag."""
    reg.tags[tag] = D1
    _pin_staging(at_staging, tag)
    rc, out = attempt(prod(at_staging), capsys)
    assert rc != 0 and f"the staging image cannot be identified: {tag}" in out and unchanged(at_staging)


def test_the_override_does_not_cover_an_unidentifiable_staging_tag(at_staging, reg, capsys):
    """AC-106.8 / AC-106.7: the override leaves this refusal."""
    reg.tags["latest"] = D1
    _pin_staging(at_staging, "latest")
    rc, out = attempt(prod(at_staging, "--accept-digest-mismatch", REASON), capsys)
    assert rc != 0 and "cannot be identified" in out and "unrecognized" not in out


# ---------------- AC-106.9 ----------------

LINE = f"image digest: {D1} (same in staging and prod)"


def test_a_match_shows_the_digest_line_in_the_output_and_the_pr_body(at_staging, monkeypatch, capsys):
    """AC-106.9: the shared digest line in the evidence and in the PR body."""
    opened = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: opened.append(body) or "https://github.com/acme/g/pull/9")
    rc, out = attempt(prod(at_staging, "--pr"), capsys)
    assert rc == 0 and LINE in out and LINE in opened[0]


def test_a_mismatch_never_prints_the_same_digest_line(at_staging, reg, capsys):
    """AC-106.9: the line is only for a match."""
    reg.tags[RELEASE] = D2
    _, out = attempt(prod(at_staging, "--dry-run"), capsys)
    assert "(same in staging and prod)" not in out


# ---------------- AC-106.10 ----------------

def _ci(template):
    text = (TEMPLATES / template / ".github" / "workflows" / "ci.yml").read_text()
    text = text.replace("${{ '{{' }}", "${{").replace("{{ '}}' }}", "}}")
    return text, yaml.safe_load(text)


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_the_release_image_job_retags_the_sha_image(template):
    """AC-106.10: on v*.*.* tags a release-image job inspects sha-${GITHUB_SHA} and creates X.Y.Z, X.Y, X with imagetools."""
    text, doc = _ci(template)
    job = doc["jobs"].get("release-image")
    assert job, f"{template}: no release-image job"
    body = yaml.safe_dump(job)
    assert "refs/tags/v" in str(job.get("if", "")) or "tag" in str(job.get("if", "")), "the job must run on release tags"
    assert "docker buildx imagetools inspect" in body and "sha-${GITHUB_SHA}" in body
    assert "docker buildx imagetools create" in body
    assert len(re.findall(r"(?:^|\s)(?:-t|--tag)\s", body)) >= 3, "X.Y.Z, X.Y and X"
    assert "no published sha-<40> image" in body
    assert "docker/build-push-action" not in body


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_the_image_build_does_not_run_on_release_tags(template):
    """AC-106.10: the build job is skipped on tags (the release is a re-tag, not a rebuild)."""
    text, doc = _ci(template)
    builds = {n: j for n, j in doc["jobs"].items() if "docker/build-push-action" in yaml.safe_dump(j)}
    assert builds, f"{template}: no build job found"
    for name, job in builds.items():
        cond = str(job.get("if", ""))
        assert re.search(r"!\s*startsWith\(github\.ref, 'refs/tags/|github\.ref_type != 'tag'", cond), f"{template}: job {name} still builds on tags"
    assert "v*.*.*" in text


# ---------------- AC-106.11 ----------------

@pytest.fixture()
def two_at_staging(gitops_repo, gh, ev, reg, capsys):  # noqa: F811
    gh.image_tags["todo-api"] |= {STAGING}
    gh.image_tags["todo-web"] |= {STAGING, "2.0.0"}
    gh.git_tags["acme/todo-web"] = ["v2.0.0"]
    composed(gitops_repo, "todo-api", "todo-web")
    promote.main(["todo-api", "todo-web", "--to", "staging", "--sha", SHA, "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    (reg.extra).extend({"name": d, "metadata": {"container": {"tags": [t]}}} for t, d in ())
    capsys.readouterr()
    return gitops_repo


def _both(repo, *extra):
    return ["todo-api", "todo-web", "--to", "prod", "--repo-dir", str(repo), *extra]


def test_one_failing_service_promotes_none_and_is_named(two_at_staging, reg, capsys):
    """AC-106.11: todo-web's mismatch stops todo-api too; todo-web is named, nothing is written."""
    # one package serves every image in the fake: todo-api matches (D1/D1); todo-web resolves in the same fake, so make it differ
    reg.tags["2.0.0"] = D2
    rc, out = attempt(_both(two_at_staging), capsys)
    assert rc != 0 and unchanged(two_at_staging) and prod_untouched(two_at_staging)
    assert "todo-web" in out and "2.0.0" in out


def test_every_failing_service_is_named(two_at_staging, reg, capsys):
    """AC-106.11: with two failing services both are named in one output."""
    reg.tags[RELEASE] = D2
    reg.tags["2.0.0"] = D3
    rc, out = attempt(_both(two_at_staging), capsys)
    assert rc != 0 and unchanged(two_at_staging)
    assert "todo-api" in out and "todo-web" in out and D2 in out and D3 in out


# ---------------- AC-106.12 ----------------

@pytest.mark.parametrize("doc", ["plugins/instance/commands/promote.md", "docs/unattended-delivery.md"])
def test_the_docs_state_the_digest_rule_the_dry_run_and_the_override(doc):
    """AC-106.12: digest rule, dry-run output and the override are described."""
    text = (ROOT / doc).read_text()
    assert "--accept-digest-mismatch" in text
    assert "digest" in text and "mismatch" in text and "--dry-run" in text
    assert "staging tested" in text

