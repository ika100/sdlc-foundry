# Design — 217 A Java library shape

The tooling is the `service-java` template's ([ADR-009](../../adr/009-service-java-stack.md)); publishing follows
[ADR-125](../../adr/125-library-releases-publish-to-github-on-the-tag.md) with the registry `github-maven`; the layout of the
shape mirrors `library-typescript` (spec 215). No new ADR: every decision below applies one of these.

## Decisions

- **The service template minus the service.** `templates/library-java` renders only `*.jinja` files and keeps the service's
  JDK pin (`java_version`), Maven, Spotless (google-java-format) + the same `config/checkstyle.xml`, JUnit 5, JaCoCo with
  the 80 % line gate, the trivy/OWASP `audit`, detect-secrets, `gate.sh`, `deps.sh` + `PomDeps.java` (synced copies of the
  service's, `sync-template-copies.py`) and the `specs` workflow. It drops Spring Boot (no parent POM: every plugin version
  is pinned in the POM), Actuator, the database and observability switches, the Dockerfile, the smoke runner and every
  image recipe and CI job. One sample class (`Greetings.greet`) and its test keep the coverage gate meaningful.
- **The artifact.** `<group_id>:<project_name>`, packaging `jar`, version `0.0.0-SNAPSHOT`, `maven.compiler.release` =
  `java_version`, a sources jar (`maven-source-plugin`, `jar-no-fork`), `url` and `scm` on the GitHub repo, and
  `distributionManagement` → repository id `github`, `https://maven.pkg.github.com/<github_org>/<project_name>`. JUnit comes
  through `junit-bom` in `dependencyManagement`.
- **The tag is the version (A2).** `comprelease.next_dev` already returns `None` for a shape it does not list, so
  `/component:release` writes only the CHANGELOG; the `svc-java` release agent skips step 3 when `VERSION_FILE` is `none`
  (as the `svc-ts` one does since spec 215). `publish.sh` reads the POM's version, group, artifact and repository URL with
  `maven-help-plugin:evaluate`, decides the version the commit builds (the tag's when `HEAD` is the tagged commit and `git
  status --porcelain` is empty, otherwise the POM's) and fails with the ADR-125 message before any build when it is not the
  tag's. It then copies `pom.xml` aside (a trap restores it), sets the version with `versions-maven-plugin:set
  -DgenerateBackupPoms=false`, checks it, and runs `package` (dry run) or `deploy` with `-DskipTests -Djacoco.skip=true`
  (A5). Plugin coordinates in the script are fully qualified with a version, so the script needs no POM change.
- **Upload.** A temporary settings file (`mktemp`, removed by the trap) holds `<server><id>github</id>` with
  `${env.GITHUB_ACTOR}` (fallback `x-access-token`) and `${env.GH_TOKEN}`, so the token is never written anywhere. Before
  deploying, `curl -fsS -u` asks the registry for `<group path>/<artifact>/<version>/<artifact>-<version>.pom`: found means a
  rerun of the same tag, and the script exits 0 saying so (A4).
- **Dry run.** Everything up to the upload (version check, `versions:set`, `package`), then one line `publish: would publish
  target/<artifact>-<version>.jar as <group>:<artifact>:<version> to <url>`; no registry call and no token needed.
- **CI.** The library-typescript job set with the service-java job names: `quality`, `test`, `security` (with
  `NVD_API_KEY`), `ci-extra`, `pr-title` and `publish` (`packages: write` next to `contents: read`, the only write
  permission; `fetch-depth: 0` so the tag is in the checkout; `GH_TOKEN` from `GITHUB_TOKEN`).
- **Detection (A6).** In the sniff fallback, a `pom.xml` with a `Dockerfile` or a `spring-boot` reference, or a Gradle
  build, is `service-java`; a bare `pom.xml` is `library-java`. The registry's sniff text for `service-java` names the new
  markers.
- **Agents.** The `svc-java` plugin serves both shapes. The release agent's input line names `none` and step 3 is skipped
  then; the coder's opening names both shapes. The changes are worded so that the prompts do not grow.
- **Shape-wide lists.** `newsvc` pair order, `deps_parse` (trivy, `pom.xml`), `buildtests` (the Java globs; the reason line
  names the repo's shape), `bump_template_pins` (the Maven updater), `template-lint` (Maven lint steps and data),
  `ci-local.sh`, the gitops-app and cluster-gitops valid pairs, `plan.py` shapes, `dependabot.yml`, the platform CI
  (`changes` output `javalib`, actionlint, the `smoke-test-library-java` job, `ci-success`) and a `smoke-java-lib` devbox
  script.

## Seams for the tests

`tests/cplat/test_217_library_java.py`: the registry, `shapes.publish_errors`, `newsvc`, `comprelease`, `deps_parse`,
`buildtests` in-process; a copier render (shared per process) for files, CI and the guide; the real `detect-shape.sh`; the
real `publish.sh` with real `git` and fake `mvn`/`curl` (`waiting.with_prelude`) that evaluate and edit the POM, write the jar
and keep the registry as files. The real toolchain (Maven, Spotless, Checkstyle, JUnit, JaCoCo, `versions:set`) runs in the
platform CI job `smoke-test-library-java`.
