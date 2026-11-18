"""Spec 209 acceptance tests: inline scripts run through uv-script.sh, so a new worktree adds no uv script environment.

Seams (design.md): `scripts/uv-script.sh` (source `templates/gitops-app/scripts/`, synced copies in `templates/cluster-gitops/scripts/`
and `scripts/`), `uvscript.script_cmd()`, the recipes in the three devbox.json files, the launcher `plugins/shared/bin/cplat`.
Script environments are the entries of `$UV_CACHE_DIR/environments-v2/`. Every run uses a tmp `UV_CACHE_DIR`, real `git worktree add`
and a hand-made local wheel as the script's dependency, so nothing touches the developer's cache or the network.
"""
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import core
import update

ROOT = core.PLATFORM_ROOT
APP = ROOT / "templates" / "gitops-app"
CLUSTER = ROOT / "templates" / "cluster-gitops"
HELPER_COPIES = [APP / "scripts" / "uv-script.sh", CLUSTER / "scripts" / "uv-script.sh", ROOT / "scripts" / "uv-script.sh"]
LAUNCHER = ROOT / "plugins" / "shared" / "bin" / "cplat"
pytestmark = pytest.mark.skipif(not shutil.which("uv") or not shutil.which("git"), reason="needs uv and git")

BLOCK = "# /// script\n# requires-python = \">=3.9\"\n# dependencies = [\"tinydep @ {url}\"]\n# ///\n"
BODY = "import os, sys\nimport tinydep\nprint(tinydep.VERSION, sys.argv[1:])\nsys.exit(int(os.environ.get('EXIT', '0')))\n"


def wheel(directory: Path, version: str) -> str:
    """A minimal pure-python wheel `tinydep` (the script's only dependency); returns its file:// URL."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"tinydep-{version}-py3-none-any.whl"
    info = f"tinydep-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("tinydep/__init__.py", f"VERSION = {version!r}\n")
        z.writestr(f"{info}/METADATA", f"Metadata-Version: 2.1\nName: tinydep\nVersion: {version}\n")
        z.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{info}/RECORD", "")
    return path.as_uri()


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.cache = tmp / "uvcache"
        self.v1 = wheel(tmp / "wheels", "1.0")
        self.v2 = wheel(tmp / "wheels", "2.0")
        drop = ("CPLAT_", "UV_", "VIRTUAL_ENV", "GATE_NAME")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(drop)} | {
            "UV_CACHE_DIR": str(self.cache), "UV_PYTHON_DOWNLOADS": "never", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def envs(self) -> int:
        d = self.cache / "environments-v2"
        return len(list(d.iterdir())) if d.is_dir() else 0

    def git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True)

    def repo(self, name: str, files: dict[str, str]) -> Path:
        repo = self.tmp / name
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        self.git(self.tmp, "init", "-q", str(repo))
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "init")
        return repo

    def worktree(self, repo: Path, n: str) -> Path:
        wt = self.tmp / f"{repo.name}-wt-{n}"
        self.git(repo, "worktree", "add", "-q", "--detach", str(wt))
        return wt

    def script(self, url: str | None = None) -> str:
        return BLOCK.format(url=url or self.v1) + BODY


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def helper() -> Path:
    """The platform's own copy, the one cplat calls by absolute path."""
    return ROOT / "scripts" / "uv-script.sh"


def run_helper(world, cwd, *args, **env):
    return subprocess.run(["bash", str(helper()), *args], cwd=cwd, env=world.env | env, capture_output=True, text=True, timeout=110)


def with_helper(files: dict[str, str]) -> dict[str, str]:
    src = next((p for p in HELPER_COPIES if p.is_file()), None)
    return files | ({"scripts/uv-script.sh": src.read_text()} if src else {})


# ---------------- AC-209.1: cplat and the helper add no environment per worktree ----------------

def test_the_helper_exists_in_the_three_places_and_the_copies_are_equal_ac_209_1():  # AC-209.1
    assert all(p.is_file() for p in HELPER_COPIES), [str(p) for p in HELPER_COPIES if not p.is_file()]
    assert len({p.read_text() for p in HELPER_COPIES}) == 1


def test_five_new_worktrees_add_no_script_environment_and_the_main_checkout_adds_none_after_removal_ac_209_1(world):  # AC-209.1
    main = world.repo("proj", with_helper({"scripts/render.py": world.script()}))
    assert run_helper(world, main, "scripts/render.py").returncode == 0
    before = world.envs()
    assert before == 1
    wts = [world.worktree(main, str(i)) for i in range(5)]
    for wt in wts:
        res = run_helper(world, wt, "scripts/render.py")
        assert res.returncode == 0, res.stderr
    assert world.envs() == before
    for wt in wts:
        world.git(main, "worktree", "remove", "--force", str(wt))
    assert run_helper(world, main, "scripts/render.py").returncode == 0
    assert world.envs() == before


def test_a_staging_worktree_removed_and_added_again_adds_no_environment_ac_209_1(world):  # AC-209.1
    main = world.repo("proj", {"scripts/render.py": world.script()})
    assert run_helper(world, main, "scripts/render.py").returncode == 0
    before = world.envs()
    for _ in range(2):
        wt = world.worktree(main, "staging")
        assert run_helper(world, wt, "scripts/render.py").returncode == 0
        world.git(main, "worktree", "remove", "--force", str(wt))
    assert world.envs() == before


def test_script_cmd_builds_the_helper_argv_ac_209_1():  # AC-209.1
    import uvscript
    assert uvscript.HELPER == ROOT / "scripts" / "uv-script.sh"
    assert uvscript.script_cmd("scripts/render.py") == ["bash", str(uvscript.HELPER), "scripts/render.py"]
    assert uvscript.script_cmd("scripts/plan.py", "done", "s", "r", quiet=True) == [
        "bash", str(uvscript.HELPER), "--quiet", "scripts/plan.py", "done", "s", "r"]


@pytest.mark.parametrize("module", ["gitops", "update", "clusterrepo", "appship", "appship_joint"])
def test_cplat_call_sites_no_longer_run_scripts_with_uv_run_ac_209_1(module):  # AC-209.1
    text = (ROOT / "scripts" / "cplat" / f"{module}.py").read_text()
    assert not re.search(r"""["']uv["']\s*,\s*["']run["']""", text), f"{module}.py still starts `uv run` itself"
    assert "script_cmd" in text


def captured_argv(monkeypatch, module, call):
    """Run `call` with the module's `run` replaced; returns the argv it tried to start (what the site runs, whatever its spelling)."""
    seen = []
    monkeypatch.setattr(module, "run", lambda argv, **kw: seen.append(list(argv)) or subprocess.CompletedProcess(argv, 0, "", ""))
    try:
        call()
    except Exception:  # noqa: BLE001  (only the first command matters; what follows needs a real repo)
        pass
    return seen


def test_the_render_sites_run_script_cmd_ac_209_1(monkeypatch, tmp_path):  # AC-209.1
    import clusterrepo
    import gitops
    import update
    import uvscript
    want = uvscript.script_cmd("scripts/render.py")
    assert captured_argv(monkeypatch, gitops, lambda: gitops.render(tmp_path))[:1] == [want]
    assert captured_argv(monkeypatch, clusterrepo, lambda: clusterrepo._render(tmp_path, ""))[:1] == [want]
    assert captured_argv(monkeypatch, update, lambda: update.rerender_cluster(tmp_path, set()))[:1] == [want]


def test_the_joint_pr_devbox_call_goes_through_the_helper_ac_209_1(monkeypatch, tmp_path):  # AC-209.1
    import appship_joint
    import uvscript
    seen = []
    monkeypatch.setattr(appship_joint, "run", lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    appship_joint._devbox(tmp_path, "scripts/plan.py", "done", "s", "r")
    assert seen == [["devbox", "run", "--", *uvscript.script_cmd("scripts/plan.py", "done", "s", "r")]]


def test_the_launcher_in_new_worktrees_of_the_platform_repo_adds_no_environment_ac_209_1(world):  # AC-209.1
    files = with_helper({
        ".platform-settings.yml": "shape: platform\n",
        "scripts/cplat/cplat.py": "#!/usr/bin/env python3\n" + world.script(),
    })
    main = world.repo("platform", files)
    env = world.env | {"XDG_CACHE_HOME": str(world.tmp / "xdg")}
    run = lambda cwd: subprocess.run(["bash", str(LAUNCHER), "x"], cwd=cwd, env=env, capture_output=True, text=True, timeout=110)  # noqa: E731
    assert run(main).returncode == 0
    before = world.envs()
    for i in range(3):
        res = run(world.worktree(main, str(i)))
        assert res.returncode == 0, res.stderr
    assert world.envs() == before


def test_the_launcher_runs_cplat_through_the_helper_and_keeps_a_fallback_ac_209_1():  # AC-209.1
    text = LAUNCHER.read_text()
    assert 'exec bash "$root/scripts/uv-script.sh" "$root/scripts/cplat/cplat.py"' in text
    assert 'exec uv run "$root/scripts/cplat/cplat.py"' in text  # a CPLAT_REF older than this release


# ---------------- recipes: structure and behaviour ----------------

def recipes(path: Path) -> dict[str, str]:
    scripts = json.loads(path.read_text())["shell"]["scripts"]
    return {k: v if isinstance(v, str) else "\n".join(v) for k, v in scripts.items()}


def block_scripts() -> set[str]:
    found = set()
    for d in (ROOT / "scripts", ROOT / "scripts" / "cplat", APP / "scripts", CLUSTER / "scripts"):
        found |= {p.name for p in d.glob("*.py") if "\n# /// script\n" in "\n" + p.read_text()}
    return found


def bare_uv_runs(text: str) -> list[str]:
    """`uv run [--quiet] <path>.py` of a script that has a PEP 723 block: the call that leaks one environment per path.
    cplat.py run from the per-ref platform cache (`"$dir/scripts/cplat/cplat.py"`, spec-check.sh and alert-poll.sh) is no leak:
    that path is fixed per platform ref, not per worktree (design.md)."""
    blocks = block_scripts()
    hits = re.findall(r'\buv run (?:--quiet )?("?[^\s"]*?([\w.-]+\.py)"?)', text)
    return [h[0] for h in hits if h[1] in blocks and not h[0].startswith('"$dir/scripts/cplat/')]


def run_recipe(world, cwd, command):
    return subprocess.run(["bash", "-c", command], cwd=cwd, env=world.env | {"BASE_REF": "HEAD"}, capture_output=True, text=True, timeout=110)


def stub_repo(world, name, commands, template):
    files = {}
    for cmd in commands:
        for m in re.findall(r"scripts/([\w-]+\.py)", cmd):
            files[f"scripts/{m}"] = world.script()
    return world.repo(name, files | ({"scripts/uv-script.sh": (template / "scripts" / "uv-script.sh").read_text()}
                                      if (template / "scripts" / "uv-script.sh").is_file() else {}))


def inline_segments(cmd: str) -> list[str]:
    """The parts of a long recipe that run an inline script (`uv run scripts/x.py …` or the helper), run without the rest."""
    blocks = block_scripts()
    found = re.finditer(r"(?:\buv run|\bbash scripts/uv-script\.sh)(?: --quiet)? scripts/([\w-]+\.py)[^&;|]*", cmd)
    return [m.group(0) for m in found if m.group(1) in blocks]


def assert_recipes_add_nothing_in_worktrees(world, devbox: Path, names: list[str], template: Path, worktrees=3, segments=False):
    scripts = recipes(devbox)
    cmds = [scripts[n] for n in names]
    if segments:
        cmds = [seg for c in cmds for seg in inline_segments(c)]
        names = [f"segment {i}" for i in range(len(cmds))]
        assert cmds, "no inline script command found in the recipes"
    repo = stub_repo(world, "gen", cmds, template)
    for n, cmd in zip(names, cmds):
        res = run_recipe(world, repo, cmd)
        assert res.returncode == 0, (n, res.stderr)
    before = world.envs()
    for i in range(worktrees):
        wt = world.worktree(repo, str(i))
        for n, cmd in zip(names, cmds):
            res = run_recipe(world, wt, cmd)
            assert res.returncode == 0, (n, res.stderr)
    assert world.envs() == before, "a recipe added a script environment in a new worktree"


APP_RECIPES = ["render", "render-check", "service-crds", "plan-check", "pin", "upgrade-check", "test-fast"]
CLUSTER_RECIPES = ["render", "render-check", "check", "test-fast"]


# ---------------- AC-209.2: the gitops-app and cluster-gitops recipes ----------------

def test_gitops_app_recipes_in_new_worktrees_add_no_script_environment_ac_209_2(world):  # AC-209.2
    assert_recipes_add_nothing_in_worktrees(world, APP / "devbox.json", APP_RECIPES, APP)


def test_cluster_gitops_recipes_in_new_worktrees_add_no_script_environment_ac_209_2(world):  # AC-209.2
    assert_recipes_add_nothing_in_worktrees(world, CLUSTER / "devbox.json", CLUSTER_RECIPES, CLUSTER)


@pytest.mark.parametrize("template", [APP, CLUSTER], ids=["gitops-app", "cluster-gitops"])
def test_no_template_recipe_or_script_starts_an_inline_script_with_uv_run_ac_209_2(template):  # AC-209.2
    leaks = {k: bare_uv_runs(v) for k, v in recipes(template / "devbox.json").items() if bare_uv_runs(v)}
    for sh in (template / "scripts").glob("*.sh"):
        if bare_uv_runs(sh.read_text()):
            leaks[sh.name] = bare_uv_runs(sh.read_text())
    assert not leaks


def test_the_gitops_app_has_a_plan_recipe_through_the_helper_ac_209_2():  # AC-209.2
    assert recipes(APP / "devbox.json").get("plan") == 'bash scripts/uv-script.sh scripts/plan.py "$@"'


def test_the_helper_runs_in_the_cluster_scripts_with_quiet_ac_209_2():  # AC-209.2
    for name in ("bootstrap.sh", "cluster-up.sh"):
        assert "bash scripts/uv-script.sh --quiet scripts/" in (CLUSTER / "scripts" / name).read_text(), name


# ---------------- AC-209.3: the platform's own recipes ----------------

def test_the_platform_recipes_inline_script_calls_in_new_worktrees_add_no_script_environment_ac_209_3(world):  # AC-209.3
    assert_recipes_add_nothing_in_worktrees(world, ROOT / "devbox.json", ["validate", "shapes-check", "quality"], ROOT.joinpath("."),
                                            segments=True)


def test_no_platform_recipe_or_script_starts_an_inline_script_with_uv_run_ac_209_3():  # AC-209.3
    leaks = {k: bare_uv_runs(v) for k, v in recipes(ROOT / "devbox.json").items() if bare_uv_runs(v)}
    for rel in ("scripts/ci-local.sh", "scripts/test-plan.sh", "scripts/test-detect-shape.sh"):
        if bare_uv_runs((ROOT / rel).read_text()):
            leaks[rel] = bare_uv_runs((ROOT / rel).read_text())
    assert not leaks
    for name in ("validate", "shapes-check", "quality"):
        assert "uv-script.sh" in recipes(ROOT / "devbox.json")[name], name


# ---------------- AC-209.4: /platform:update ----------------

def previous_release_devbox(template: Path) -> dict:
    """The template's devbox.json at the last release tag; without a tag, the current one with the helper swapped back to `uv run`."""
    tags = subprocess.run(["git", "tag", "--sort=-v:refname", "--merged", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if tags:
        shown = subprocess.run(["git", "show", f"{tags[0]}:templates/{template.name}/devbox.json"], cwd=ROOT, capture_output=True, text=True)
        if shown.returncode == 0:
            return json.loads(shown.stdout)
    old = json.loads((template / "devbox.json").read_text())
    for name, cmd in old["shell"]["scripts"].items():
        if isinstance(cmd, str):
            old["shell"]["scripts"][name] = cmd.replace("bash scripts/uv-script.sh", "uv run")
    old["shell"]["scripts"].pop("plan", None)
    return old


@pytest.mark.parametrize("template", [APP, CLUSTER], ids=["gitops-app", "cluster-gitops"])
def test_update_from_the_previous_release_replaces_no_recipe_and_brings_the_helper_ac_209_4(template):  # AC-209.4
    new = json.loads((template / "devbox.json").read_text())
    old = previous_release_devbox(template)
    assert not any("uv-script.sh" in str(v) for v in old["shell"]["scripts"].values())
    merged, _, replaced = update.merge_devbox(json.loads(json.dumps(old)), new, old)
    assert replaced == []
    assert merged["shell"]["scripts"] == new["shell"]["scripts"]
    assert "bash scripts/uv-script.sh" in merged["shell"]["scripts"]["render"]  # the repo got the helper's recipes, no edit by hand
    assert (template / "scripts" / "uv-script.sh").is_file()


# ---------------- AC-209.5: each dependency list has its own environment ----------------

def test_a_changed_dependency_list_runs_with_its_own_environment_and_adds_one_ac_209_5(world):  # AC-209.5
    main = world.repo("proj", with_helper({"scripts/x.py": world.script(world.v1)}))
    changed = world.worktree(main, "changed")
    (changed / "scripts" / "x.py").write_text(world.script(world.v2))
    other = world.worktree(main, "other")
    outs = []
    for _ in range(3):
        for wt in (changed, other, main, world.worktree(main, f"n{len(outs)}")):
            res = run_helper(world, wt, "scripts/x.py")
            assert res.returncode == 0, res.stderr
            outs.append((wt == changed, res.stdout))
    assert {o for c, o in outs if c} == {"2.0 []\n"}
    assert {o for c, o in outs if not c} == {"1.0 []\n"}
    # at most one environment for each of the two lists (uv 0.11 shares one base environment for both, so 1 is as good as 2)
    assert 1 <= world.envs() <= 2


# ---------------- AC-209.6: concurrent runs ----------------

def test_three_runs_at_once_succeed_with_the_same_output_and_add_one_environment_ac_209_6(world):  # AC-209.6
    main = world.repo("proj", {"scripts/x.py": world.script()})
    alone = run_helper(world, main, "scripts/x.py", "a")
    assert alone.returncode == 0
    shutil.rmtree(world.cache)
    wts = [world.worktree(main, str(i)) for i in range(3)]
    procs = [subprocess.Popen(["bash", str(helper()), "scripts/x.py", "a"], cwd=wt, env=world.env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for wt in wts]
    try:
        results = [(p.communicate(timeout=110), p.returncode) for p in procs]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()
    for (out, err), code in results:
        assert code == alone.returncode, err
        assert out == alone.stdout
    assert world.envs() <= 1


# ---------------- AC-209.7: the same output, files and exit code ----------------

def test_the_helper_passes_arguments_exit_code_output_cwd_and_the_scripts_own_path_ac_209_7(world):  # AC-209.7
    body = ("import os, sys\nimport tinydep\nprint('out', tinydep.VERSION, sys.argv[1:], __file__, os.getcwd())\n"
            "print('err', file=sys.stderr)\nopen('written.txt', 'w').write(sys.stdin.read())\nsys.exit(7)\n")
    main = world.repo("proj", {"scripts/x.py": BLOCK.format(url=world.v1) + body})
    wt = world.worktree(main, "a")
    for cwd in (main, wt):
        res = subprocess.run(["bash", str(helper()), "scripts/x.py", "a b", "--c"], cwd=cwd, env=world.env, input="stdin text",
                             capture_output=True, text=True, timeout=110)
        assert res.returncode == 7
        assert res.stdout.strip() == f"out 1.0 ['a b', '--c'] scripts/x.py {cwd.resolve()}" or \
            res.stdout.strip() == f"out 1.0 ['a b', '--c'] {cwd / 'scripts/x.py'} {cwd.resolve()}" or \
            res.stdout.strip() == f"out 1.0 ['a b', '--c'] {cwd.resolve() / 'scripts/x.py'} {cwd.resolve()}"
        assert res.stderr.strip().endswith("err")
        assert (cwd / "written.txt").read_text() == "stdin text"


def test_the_helper_gives_the_same_result_as_uv_run_for_a_script_with_a_block_ac_209_7(world):  # AC-209.7
    body = ("import os, sys\nimport tinydep\nprint('out', tinydep.VERSION, sys.argv[1:])\nprint('err', sys.argv[1:], file=sys.stderr)\n"
            "open('written.txt', 'w').write(f'{tinydep.VERSION} {sys.argv[1:]} {sys.stdin.read()}')\nsys.exit(int(os.environ.get('EXIT', '0')))\n")
    main = world.repo("proj", {"scripts/x.py": BLOCK.format(url=world.v1) + body})
    direct_wt, via_wt = world.worktree(main, "direct"), world.worktree(main, "via")
    mine = lambda r: [ln for ln in r.stderr.splitlines() if ln.startswith("err")]  # noqa: E731  (uv's own progress lines differ)
    for code in ("0", "3"):
        env = world.env | {"EXIT": code}
        direct = subprocess.run(["uv", "run", "scripts/x.py", "q"], cwd=direct_wt, env=env, input="in", capture_output=True, text=True, timeout=110)
        via = subprocess.run(["bash", str(helper()), "scripts/x.py", "q"], cwd=via_wt, env=env, input="in", capture_output=True, text=True,
                             timeout=110)
        assert (via.returncode, via.stdout, mine(via)) == (direct.returncode, direct.stdout, mine(direct)) == (
            int(code), "out 1.0 ['q']\n", ["err ['q']"])
        assert (via_wt / "written.txt").read_text() == (direct_wt / "written.txt").read_text() == "1.0 ['q'] in"


def test_a_script_without_a_block_and_the_quiet_flag_still_run_ac_209_7(world):  # AC-209.7
    main = world.repo("proj", {"scripts/plain.py": "import sys\nprint('plain', sys.argv[1:])\nsys.exit(4)\n", "scripts/x.py": world.script()})
    res = run_helper(world, main, "scripts/plain.py", "z")
    assert (res.returncode, res.stdout) == (4, "plain ['z']\n")
    res = run_helper(world, main, "--quiet", "scripts/x.py", "z")
    assert (res.returncode, res.stdout) == (0, "1.0 ['z']\n")


def test_the_helper_runs_under_the_system_bash_with_a_missing_script_failing_like_uv_ac_209_7(world):  # AC-209.7
    main = world.repo("proj", {"scripts/x.py": world.script()})
    res = subprocess.run(["/bin/bash", str(helper()), "scripts/x.py"], cwd=main, env=world.env, capture_output=True, text=True, timeout=110)
    assert (res.returncode, res.stdout) == (0, "1.0 []\n")
    res = subprocess.run(["/bin/bash", str(helper()), "scripts/missing.py"], cwd=main, env=world.env, capture_output=True, text=True, timeout=110)
    assert res.returncode != 0


def test_the_github_actions_workflows_do_not_use_the_helper_ac_209_7():  # AC-209.7
    workflows = list((APP / ".github").rglob("*")) + list((CLUSTER / ".github").rglob("*")) + list((ROOT / ".github" / "workflows").glob("*"))
    assert [w for w in workflows if w.is_file() and "uv-script.sh" in w.read_text()] == []
    assert HELPER_COPIES[0].is_file()  # the helper exists, so this is not vacuous


def test_the_system_prompts_call_the_plan_recipe_ac_209_7():  # AC-209.7
    for rel in ("plugins/system/commands/plan.md", "plugins/system/references/spec-list.md"):
        text = (ROOT / rel).read_text()
        assert "uv run scripts/plan.py" not in text, rel
        assert "devbox run plan" in text, rel
