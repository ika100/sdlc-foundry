"""One behind repo of `cplat fleet update` (spec 096): branch, update, push, PR, routine check, label/comment, CI wait + merge.

The update itself is `update.resolve` + `update.execute` on a fresh clone, so the commit is exactly what
`/shared:update-service` makes. See docs/specs/096-platform-updates-roll-out-to-every-repo/design.md.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import core
import pr
import ship
import update as upd
from core import PlatformError, run

LABEL = "platform-update: needs review"
MARKER = "<!-- cplat-fleet -->"
BRANCH_PREFIX = "chore/platform-update-"
UPDATE_SUBJECT = "chore: update skeleton from platform "
BODY_LIMIT = 60000
CUT = "\n… (cut; see docs/CHANGELOG.md of sdlc-foundry)"
CHANGELOG_URL = "https://github.com/ika100/sdlc-foundry/blob/v{target}/docs/CHANGELOG.md"
_FOLLOW_UP_DROPPED = ("run the repo's checks:", "platform changes since your version")


@dataclass
class Ctx:
    slug: str
    clone: Path                 # fresh clone, default branch checked out, clean
    default_branch: str
    gh: Callable[..., tuple[int, str, str]]
    sleep: Callable[[float], None]
    timeout: float              # CI wait per PR


@dataclass
class Result:
    outcome: str                # "up to date" | "merged" | "left open" | "failed"
    reason: str | None
    pr: str | None              # PR URL
    next: list[str]


def _first(text: str) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[0].strip() if lines else ""


def _git(ctx: Ctx, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=ctx.clone, check=check).stdout.strip()


def _gh(ctx: Ctx, step: str, args: list[str], input: str | None = None) -> str:
    rc, out, err = ctx.gh(args, input=input)
    if rc != 0:
        raise PlatformError(f"{step}: {_first(err) or _first(out) or 'failed'}")
    return out


def open_fleet_pr(ctx: Ctx) -> dict | None:
    rc, out, err = ctx.gh(["pr", "list", "-R", ctx.slug, "--state", "open", "--json", "number,url,headRefName,labels",
                           "--limit", "100"])
    if rc != 0:
        raise PlatformError(f"pr list: {_first(err) or 'failed'}")
    prs = [p for p in json.loads(out or "[]") if str(p.get("headRefName", "")).startswith(BRANCH_PREFIX)]
    return max(prs, key=lambda p: p["number"]) if prs else None


def new_branch(ctx: Ctx) -> str:
    base = upd.branch_name()
    refs = _git(ctx, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin").splitlines()
    taken = {r.removeprefix("refs/heads/").removeprefix("refs/remotes/origin/") for r in refs}
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def follow_ups(report: core.Report) -> list[str]:
    return [s for s in report.next_steps if not s.startswith(_FOLLOW_UP_DROPPED)]


def _major(v: str) -> int:
    return core.vtuple(v)[0]


def _proved_migration(old: str, target: str, data: dict) -> bool:
    """AC-114.68: a 4 → 5 migration that proved its render and overwrote nothing merges although it is a major version."""
    mig = data.get("migration") or {}
    return bool(mig.get("ran") and _major(old) == 4 and _major(target) == 5 and not data.get("lost")
                and (mig.get("kind") == "component" or mig.get("byte_identical") is True))


def pre_wait_reasons(old: str | None, target: str, data: dict) -> list[str]:
    reasons = []
    if data.get("lost"):
        reasons.append("local customisation")
    if old is None:
        reasons.append(f"major version unknown → {_major(target)}")
    elif _major(old) < _major(target) and not _proved_migration(old, target, data):
        reasons.append(f"major version {_major(old)} → {_major(target)}")
    return reasons


def _lost_line(e: dict) -> str:
    entry = f" `{e['entry']}`" if e.get("entry") else ""
    return f"- `{e['file']}`{entry}: {e.get('where', '')}"


def pr_body(old: str | None, target: str, data: dict, next_steps: list[str]) -> str:
    was = old or "none"
    changed = data.get("changed") or []
    dev = data.get("devbox") or {}
    kept = "; ".join(dev.get("kept") or []) or "none"
    replaced = "; ".join(f"`{r['entry']}` (was `{r['was']}`)" for r in dev.get("replaced") or []) or "none"
    lines = [MARKER,
             f"Platform update **{was} → {target}** by `cplat fleet update` (spec 096); the same commit "
             "`/platform:update` makes.", "",
             f"### Changed files ({len(changed)})", *[f"- `{p}`" for p in changed],
             "### devbox.json", f"- kept: {kept}", f"- replaced by the template: {replaced}"]
    if dev.get("moved_to_ci_extra"):
        lines.append("- moved to ci-extra: " + ", ".join(dev["moved_to_ci_extra"]))
    if dev.get("dropped_gates"):
        lines.append("- dropped gates: " + ", ".join(dev["dropped_gates"]))
    lines.append("### Overwritten customisations (spec 086)")
    lines += [_lost_line(e) for e in data.get("lost") or []] or ["- none"]
    if data.get("baseline") is None:
        lines.append(f"No baseline for {was}: every difference counts as overwritten.")
    lines.append("### Follow-up steps")
    lines += [f"- {s}" for s in next_steps] or ["- none"]
    head = "\n".join(lines) + f"\n### Platform changes {was} → {target}\n"
    notes = data.get("changelog") or "none recorded"
    if len(head) + len(notes) > BODY_LIMIT:
        notes = notes[:max(0, BODY_LIMIT - len(head) - len(CUT))] + CUT
    return head + notes


def comment_body(slug: str, old: str | None, target: str, reasons: list[str], lost: list[dict]) -> str:
    parts = [MARKER, f"**The platform fleet update left this PR open:** {'; '.join(reasons)}", ""]
    if "local customisation" in reasons:
        parts += ["This update overwrote what the repo added (spec 086):", *[_lost_line(e) for e in lost], ""]
    if any(r.startswith("major version") for r in reasons):
        first = _major(old) + 1 if old else _major(target)
        parts += [f"Major platform update {old or 'unknown'} → {target} is never merged automatically. Read the migration notes "
                  f"for {k}.0.0 in {CHANGELOG_URL.format(target=target)}" for k in range(first, _major(target) + 1)]
        parts.append("")
    parts.append(f"Review and merge it by hand, or run `cplat fleet update --only {slug}` again after a fix.")
    return "\n".join(parts) + "\n"


def _mergeable(ctx: Ctx, url: str) -> str:
    state = "UNKNOWN"
    for i in range(11):
        rc, out, _ = ctx.gh(["pr", "view", url, "-R", ctx.slug, "--json", "mergeable"])
        state = (json.loads(out or "{}").get("mergeable") or "UNKNOWN") if rc == 0 else "UNKNOWN"
        if state != "UNKNOWN" or i == 10:
            break
        ctx.sleep(3)
    return state


def _leave_open(ctx: Ctx, url: str, labelled: bool, old: str | None, target: str, reasons: list[str], lost: list[dict]) -> None:
    if not labelled:
        ctx.gh(["label", "create", LABEL, "-R", ctx.slug, "--color", "D93F0B", "--description",
                "A platform fleet update needs a person (spec 096)"])        # an existing label is fine
        _gh(ctx, "label", ["pr", "edit", url, "-R", ctx.slug, "--add-label", LABEL])
    body = comment_body(ctx.slug, old, target, reasons, lost)
    _, out, _ = ctx.gh(["pr", "view", url, "-R", ctx.slug, "--json", "comments"])
    try:
        mine = [c.get("body", "") for c in json.loads(out or "{}").get("comments") or [] if MARKER in c.get("body", "")]
    except ValueError:
        mine = []
    if not mine or mine[-1].strip() != body.strip():
        _gh(ctx, "comment", ["pr", "comment", url, "-R", ctx.slug, "--body-file", "-"], input=body)


def _wait(ctx: Ctx, url: str) -> tuple[str, str | None]:
    """pr wait --merge -> (outcome, reason)."""
    try:
        ok, lines = pr.wait(ctx.clone, url, True, ctx.timeout, 20, ship.QUEUE_TIMEOUT, ctx.slug)
    except PlatformError as e:
        msg = str(e)
        if msg.startswith("no CI checks"):
            return "left open", "no CI checks"
        if "still pending" in msg:
            return "left open", f"CI still pending after {ctx.timeout:g}s"
        if msg.startswith("merging "):
            if _mergeable(ctx, url) == "CONFLICTING":
                return "left open", "merge conflict"
            return "left open", f"merge failed: {_first(msg)}"
        return "left open", f"CI wait failed: {_first(msg)}"
    if ok:
        return "merged", None
    first = lines[0] if lines else "check failed"
    marker = f" on {url}: "
    return "left open", "red CI: " + (first.split(marker, 1)[1] if marker in first else first)


def _manual_commits(ctx: Ctx, head: str) -> bool:
    subjects = _git(ctx, "log", "--no-merges", "--format=%s", f"origin/{ctx.default_branch}..origin/{head}").splitlines()
    return any(s and not s.startswith(UPDATE_SUBJECT) for s in subjects)


def update(ctx: Ctx, old: str | None, target: str, ref: str | None) -> Result:  # noqa: A001  (the contract's name)
    existing = open_fleet_pr(ctx)
    head = existing["headRefName"] if existing else None
    if head and _manual_commits(ctx, head):
        return _manual(ctx, existing, head, old, target)
    branch = head or new_branch(ctx)
    _git(ctx, "checkout", "-q", "-b", branch)
    report = _run_update(ctx, ref, old, target)
    if not report.data:
        return Result("up to date", None, existing["url"] if existing else None, [])
    nxt = follow_ups(report)
    if head:
        sha = _git(ctx, "rev-parse", f"origin/{head}")
        if _git(ctx, "rev-parse", "HEAD^{tree}") != _git(ctx, "rev-parse", f"origin/{head}^{{tree}}"):
            _git(ctx, "push", "-q", f"--force-with-lease={head}:{sha}", "origin", branch)
    else:
        _git(ctx, "push", "-q", "-u", "origin", branch)
    title = f"chore: platform update {old or 'none'} → {target}"
    body = pr_body(old, target, report.data, nxt)
    if existing:
        url = existing["url"]
        _gh(ctx, "pr edit", ["pr", "edit", url, "-R", ctx.slug, "--title", title, "--body-file", "-"], input=body)
    else:
        out = _gh(ctx, "pr create", ["pr", "create", "-R", ctx.slug, "--base", ctx.default_branch, "--head", branch,
                                     "--title", title, "--body-file", "-"], input=body)
        url = [ln.strip() for ln in out.splitlines() if ln.strip()][-1]
    labelled = bool(existing) and any(lb.get("name") == LABEL for lb in existing.get("labels") or [])
    try:
        return _decide(ctx, url, labelled, old, target, report.data, nxt)
    except Exception as e:  # noqa: BLE001  (the PR exists: keep its link in the report)
        return Result("failed", _first(str(e)) or type(e).__name__, url, nxt)


def _run_update(ctx: Ctx, ref: str | None, old: str | None = None, target: str | None = None) -> core.Report:
    migrate = old is not None and target is not None and _major(old) < 5 <= _major(target)
    req = upd.resolve(["--repo", str(ctx.clone)] + (["--ref", ref] if ref else []) + (["--migrate"] if migrate else []))
    try:
        return upd.execute(req)
    except Exception as e:  # noqa: BLE001
        lines = [ln.strip() for ln in str(e).strip().splitlines() if ln.strip()]
        if migrate and lines and lines[0].startswith("cannot migrate"):   # the bad keys are on the lines after the first
            raise RuntimeError(" ".join(lines)) from e
        raise


def _decide(ctx: Ctx, url: str, labelled: bool, old: str | None, target: str, data: dict, nxt: list[str]) -> Result:
    lost = data.get("lost") or []
    reasons = pre_wait_reasons(old, target, data)
    if not reasons:
        if _mergeable(ctx, url) == "CONFLICTING":
            reasons = ["merge conflict"]
        else:
            outcome, reason = _wait(ctx, url)
            if outcome == "merged":
                return Result("merged", None, url, nxt)
            reasons = [reason or "CI wait failed"]
    _leave_open(ctx, url, labelled, old, target, reasons, lost)
    return Result("left open", "; ".join(reasons), url, nxt)


def _manual(ctx: Ctx, existing: dict, head: str, old: str | None, target: str) -> Result:
    url = existing["url"]
    reason = f"manual commits on {head}"
    try:
        _leave_open(ctx, url, any(lb.get("name") == LABEL for lb in existing.get("labels") or []), old, target, [reason], [])
    except Exception as e:  # noqa: BLE001
        return Result("failed", _first(str(e)) or type(e).__name__, url, [])
    return Result("left open", reason, url, [])
