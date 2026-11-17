"""Spec 204: service-java on Spring Boot 4.x, distroless debian13 runtime, empty accepted list, CI proof of the contract."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

import newsvc

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "service-java"
CI = ROOT / ".github" / "workflows" / "ci.yml"
ACCEPTED = ROOT / ".github" / "image-scan-accepted.yml"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def _generate(tmp_path_factory, name, *data):
    base = tmp_path_factory.mktemp(name)
    argv = [name, "desc", "--type", "service", "--lang", "java", "--no-github", "--skip-tasks", "--dir", str(base), "--org", "acme"]
    for kv in data:
        argv += ["--data", kv]
    assert newsvc.main(argv) == 0
    return base / name


@pytest.fixture(scope="module")
def default_repo(tmp_path_factory):
    return _generate(tmp_path_factory, "def-svc")


@pytest.fixture(scope="module")
def db_repo(tmp_path_factory):
    return _generate(tmp_path_factory, "dbb-svc", "needs_database=true")


def _pom(repo):
    root = ET.fromstring((repo / "pom.xml").read_text())
    parent = root.find("m:parent", NS)
    deps = {d.findtext("m:artifactId", namespaces=NS) for d in root.findall("m:dependencies/m:dependency", NS)}
    props = {p.tag.split("}")[1] for p in root.find("m:properties", NS)}
    return parent, deps, props


def _ci():
    return yaml.safe_load(CI.read_text())


def _java_smoke_text():
    return yaml.safe_dump(_ci()["jobs"]["smoke-test-service-java"])


# AC-204.1
def test_pom_parent_is_spring_boot_4_ga_ac_204_1(default_repo):  # AC-204.1
    parent, _, _ = _pom(default_repo)
    assert parent.findtext("m:artifactId", namespaces=NS) == "spring-boot-starter-parent"
    version = parent.findtext("m:version", namespaces=NS)
    assert re.fullmatch(r"4\.\d+\.\d+", version), version


def test_pom_has_no_stale_overrides_ac_204_1(default_repo):  # AC-204.1
    _, _, props = _pom(default_repo)
    assert not props & {"tomcat.version", "jackson-bom.version", "spring-framework.version"}
    assert "java.version" in props


def test_default_pom_uses_boot_4_starters_ac_204_1(default_repo):  # AC-204.1
    _, deps, _ = _pom(default_repo)
    assert {"spring-boot-starter-webmvc", "spring-boot-starter-actuator", "spring-boot-starter-test",
            "spring-boot-starter-webmvc-test"} <= deps
    assert "spring-boot-starter-web" not in deps


def test_ci_default_variant_checks_spring_webmvc_jar_version_ac_204_1():  # AC-204.1
    text = _java_smoke_text()
    assert "spring-webmvc-" in text and "7.0.9" in text and "sort -V" in text
    steps = _ci()["jobs"]["smoke-test-service-java"]["steps"]
    run = "\n".join(s.get("run", "") for s in steps if "sort -V" in s.get("run", ""))
    assert "app.jar" in run and "BOOT-INF/lib" in run


# AC-204.2
def test_pom_with_database_and_observability_deps_ac_204_2(db_repo):  # AC-204.2
    _, deps, _ = _pom(db_repo)
    assert {"spring-boot-starter-data-jpa", "spring-boot-starter-validation", "spring-boot-starter-flyway", "flyway-core",
            "flyway-database-postgresql", "postgresql", "spring-boot-testcontainers", "testcontainers-junit-jupiter",
            "testcontainers-postgresql", "micrometer-registry-prometheus"} <= deps


def test_ci_matrix_has_all_four_variants_ac_204_2():  # AC-204.2
    matrix = _ci()["jobs"]["smoke-test-service-java"]["strategy"]["matrix"]["include"]
    combos = {(bool(m["observability"]), bool(m["database"])) for m in matrix}
    assert combos == {(True, True), (True, False), (False, True), (False, False)}
    assert "postgres:17" in _java_smoke_text()


def test_template_trivyignore_drops_the_spring_framework_6_entry_ac_204_1():  # AC-204.1
    assert "CVE-2026-47884" not in (TEMPLATE / ".trivyignore").read_text()


# AC-204.3
def test_dockerfile_runtime_is_distroless_debian13_nonroot_ac_204_3(default_repo):  # AC-204.3
    text = (default_repo / "Dockerfile").read_text()
    froms = [ln for ln in text.splitlines() if ln.startswith("FROM ")]
    assert froms[-1] == "FROM gcr.io/distroless/java21-debian13:nonroot AS runtime"
    assert "debian12" not in text and "USER 65532:65532" in text and "HEALTHCHECK" not in text


def test_ci_image_step_checks_the_image_contract_ac_204_3():  # AC-204.3
    text = _java_smoke_text()
    assert "--user 65532:65532" in text and "--read-only" in text
    assert "health/liveness" in text and "health/readiness" in text
    assert "/actuator/prometheus" in text
    steps = _ci()["jobs"]["smoke-test-service-java"]["steps"]
    image_run = "\n".join(s["run"] for s in steps if "docker build" in s.get("run", ""))
    sh_lines = [ln.strip() for ln in image_run.splitlines() if "--entrypoint sh" in ln]
    assert sh_lines and all(ln.startswith(("!", "if ")) for ln in sh_lines), sh_lines
    assert "java -version" in image_run and ".copier-answers.yml" in image_run
    run = "\n".join(s.get("run", "") for s in steps)
    assert "seq 1 20" in run, "readiness/liveness must be awaited 20 x 3 s = 60 s"


# AC-204.4
def test_default_dockerfile_names_debian13_and_not_debian12_ac_204_4(default_repo):  # AC-204.4
    text = (default_repo / "Dockerfile").read_text()
    assert "debian13" in text and "debian12" not in text


def test_template_image_scan_covers_service_java_and_accepts_nothing_ac_204_4():  # AC-204.4
    import importlib.util

    spec = importlib.util.spec_from_file_location("template_image_scan", ROOT / "scripts" / "template-image-scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "service-java" in mod.TEMPLATES
    assert yaml.safe_load(ACCEPTED.read_text())["findings"] == []


# AC-204.5
def test_accepted_list_has_no_service_java_entry_ac_204_5():  # AC-204.5
    data = yaml.safe_load(ACCEPTED.read_text())
    assert isinstance(data["findings"], list)
    assert [f for f in data["findings"] if f.get("template") == "service-java"] == []


# AC-204.6
def test_template_update_leaves_project_owned_files_ac_204_6():  # AC-204.6
    skip = yaml.safe_load((TEMPLATE / "copier.yml").read_text())["_skip_if_exists"]
    assert {"pom.xml", "src/**", ".trivyignore"} <= set(skip)


def test_ci_has_update_job_from_v5_23_3_ac_204_6():  # AC-204.6
    ci = _ci()
    job = ci["jobs"]["smoke-test-service-java-update"]
    assert "java == 'true'" in job["if"]
    assert "smoke-test-service-java-update" in ci["jobs"]["ci-success"]["needs"]
    text = yaml.safe_dump(job)
    for needle in ("v5.23.3", "git archive", "--overwrite", "--skip-tasks", "git diff --exit-code", "3.5.16",
                   "debian13", "--user 65532:65532", "--read-only", "smoke: 1 passed, 0 failed, 0 skipped"):
        assert needle in text, needle


# AC-204.7
@pytest.mark.parametrize("rel", ["CLAUDE.md", "docs/adr/000-bootstrap.md"])
def test_generated_docs_name_boot_4_and_debian13_ac_204_7(default_repo, rel):  # AC-204.7
    text = (default_repo / rel).read_text()
    assert "Spring Boot 4.x" in text
    assert "gcr.io/distroless/java21-debian13:nonroot" in text
    assert "Spring Boot 3" not in text and "debian12" not in text


def test_copier_question_help_names_boot_4_and_debian13_ac_204_7():  # AC-204.7
    text = (TEMPLATE / "copier.yml").read_text()
    assert "Spring Boot 4.x" in text and "debian13" in text
    assert "Spring Boot 3" not in text and "debian12" not in text
    help_text = yaml.safe_load(text)["java_version"]["help"]
    assert "debian13" in help_text and "gcr.io/distroless/java<jdk>-debian13:nonroot" in help_text
