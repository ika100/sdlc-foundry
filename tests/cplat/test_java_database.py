"""service-java `needs_database`: PostgreSQL support (JPA, Flyway, Testcontainers) wired to the platform's PG* variables."""
from pathlib import Path

import pytest

import newsvc


def generate(tmp_path, name, *data):
    argv = [name, "desc", "--type", "service", "--lang", "java", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]
    for kv in data:
        argv += ["--data", kv]
    assert newsvc.main(argv) == 0
    return tmp_path / name


def test_database_option_adds_jpa_flyway_driver_and_testcontainers(tmp_path):
    repo = generate(tmp_path, "db-svc", "needs_database=true")
    pom = (repo / "pom.xml").read_text()
    for artifact in ("spring-boot-starter-data-jpa", "spring-boot-starter-validation", "flyway-core", "flyway-database-postgresql", "postgresql",
                     "spring-boot-testcontainers"):
        assert f"<artifactId>{artifact}</artifactId>" in pom, artifact
    cfg = (repo / "src/main/resources/application.yml").read_text()
    assert "jdbc:postgresql://${PGHOST:localhost}:${PGPORT:5432}/${PGDATABASE:db_svc}" in cfg
    assert "username: ${PGUSER:app}" in cfg and "password: ${PGPASSWORD:dev}" in cfg
    assert "initialization-fail-timeout: 60000" in cfg      # no crash loop while the database initialises
    assert "ddl-auto: validate" in cfg and "include: readinessState,db" in cfg
    assert (repo / "src/main/resources/db/migration").is_dir()
    tests = list(repo.glob("src/test/java/**/TestcontainersConfiguration.java"))
    assert len(tests) == 1 and "@ServiceConnection" in tests[0].read_text()
    assert "@Import(TestcontainersConfiguration.class)" in next(repo.glob("src/test/java/**/ApplicationTests.java")).read_text()
    devbox = (repo / "devbox.json").read_text()
    assert '"db-up"' in devbox and "POSTGRES_DB=db_svc" in devbox
    import json
    json.loads(devbox)                                   # the conditional recipe keeps the JSON valid
    env = (repo / "docs/env-vars.md").read_text()
    assert all(v in env for v in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"))
    assert "Flyway" in (repo / "CLAUDE.md").read_text()


def test_default_service_has_no_database_files_or_dependencies(tmp_path):
    repo = generate(tmp_path, "plain-svc")
    assert "data-jpa" not in (repo / "pom.xml").read_text() and "datasource" not in (repo / "src/main/resources/application.yml").read_text()
    assert not (repo / "src/main/resources/db").exists()
    assert not list(repo.glob("src/test/java/**/TestcontainersConfiguration.java"))
    assert '"db-up"' not in (repo / "devbox.json").read_text()


@pytest.mark.parametrize("value", ["true", "false"])
def test_database_option_is_recorded_in_the_answers_so_updates_keep_it(tmp_path, value):
    repo = generate(tmp_path, "keep-svc", f"needs_database={value}")
    assert f"needs_database: {value}" in (repo / ".copier-answers.yml").read_text()
