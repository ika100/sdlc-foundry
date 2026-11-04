// The steps of the recorded demo run (2026-11-03, sdlc-foundry 5.6.0) for DemoWalkthrough.astro.
// `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from the recording,
// the demo repos and docs/BASELINES.md ("The 2026-11-03 demo run").

const API = 'https://github.com/ika100/demo-taskboard-api';
const GITOPS = 'https://github.com/ika100/demo-taskboard-gitops';
const SPEC = `${API}/blob/main/docs/specs/001-create-and-list-tasks`;
const ISSUES = 'https://github.com/ika100/sdlc-foundry/issues';
const WEB = 'https://github.com/ika100/demo-taskboard-web';
const SYS_SPEC = `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-and-web-task-list`;
const BACKUP_SPEC = `${GITOPS}/blob/main/docs/specs/002-nightly-prod-database-backups-to-an-in`;
const PLATFORM = 'https://github.com/ika100/sdlc-foundry';

export interface Section { heading: string; text?: string; items?: string[]; code?: string }
export interface Step {
  title: string; short: string;
  /** what you would say in Claude Code; empty when the step needs no input */
  say: string;
  /** the command that runs (the plugin command Claude picks for `say`, or the shell command) */
  run: string;
  /** what was typed in the recording */
  command: string; at: number;
  /** working time of the step with every wait cut (GitHub limits, people, CI queues); empty when it is part of another step */
  time: string;
  sections: Section[]; links: { label: string; href: string }[];
}

export const steps: Step[] = [
  {
    title: 'Create the system', short: 'System', say: 'Create a taskboard system with one Python service for a task API, in public repos', run: '/system:new taskboard.yaml --public', command: '/system:new taskboard.yaml --public', at: 0, time: '3 min',
    sections: [
      { heading: 'You type', text: 'A four-line manifest and one command in Claude Code.', code: 'system: demo-taskboard\nowner: ika100\nvisibility: public\ncomponents:\n  - {name: demo-taskboard-api, description: Task API, type: service, lang: python}' },
      { heading: 'Claude does', items: [
        'Previews the run with <code>--dry-run</code>, then runs <code>cplat system new</code>.',
        'Renders the gitops-app and the Python service from their templates, creates both GitHub repos and pushes them.',
        'Protects <code>main</code> on both, links the service to the gitops repo (<code>.platform-app.yml</code>), and opens one PR that adds the service to <code>system.yaml</code>.',
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image, and a list of next steps (including the <code>GITOPS_TOKEN</code> secret that lets dev follow <code>main</code>).' },
    ],
    links: [
      { label: 'demo-taskboard-gitops', href: GITOPS },
      { label: 'demo-taskboard-api', href: API },
      { label: 'PR: add the service to system.yaml', href: `${GITOPS}/pull/2` },
    ],
  },
  {
    title: 'Merge and start a local cluster', short: 'Cluster', say: 'Merge the PR once its CI is green, then start a local cluster', run: 'devbox run cluster-up', command: 'Merge PR #2 once its CI is green, then run cluster-up', at: 20.542, time: '2 min',
    sections: [
      { heading: 'Claude does', items: [
        'Waits for the PR\'s CI and merges it.',
        'Runs <code>devbox run cluster-up</code> in the gitops repo: a k3d cluster with ArgoCD and the Gateway API, then the root Application.',
        'Waits for the API repo\'s first <code>main</code> build to publish its image, then checks that Argo reports the app Synced and Healthy.',
      ] },
      { heading: 'Result', text: '<code>/health</code>, <code>/ready</code> and <code>/docs</code> answer 200.' },
    ],
    links: [{ label: 'API repo CI runs', href: `${API}/actions` }],
  },
  {
    title: 'Expose the API', short: 'Expose', say: 'Make the API reachable from my browser', run: '/component:set demo-taskboard-api --expose', command: 'yes, expose it and merge the PR once CI is green', at: 33.552, time: '2 min',
    sections: [
      { heading: 'Claude does', text: 'Runs <code>/component:set demo-taskboard-api --expose</code>: one PR that adds the route and the expose flag to <code>system.yaml</code>. Merges it after CI; Argo syncs about 20 s later.' },
      { heading: 'Result', text: 'A URL on the local Gateway: <code>http://demo-taskboard-api.demo-taskboard-dev.localhost:8088</code>. Only needed for this demo; a component declared with <code>expose</code> from the start skips it.' },
    ],
    links: [{ label: 'PR: expose the API', href: `${GITOPS}/pull/3` }],
  },
  {
    title: 'Write the spec', short: 'Spec', say: 'I want to create and list tasks, each with a title and an optional due date, kept in memory', run: '/component:spec "tasks: create and list tasks …"', command: '/component:spec "tasks: create and list tasks with a title and an optional due date, kept in memory"', at: 43.8, time: '4 min',
    sections: [
      { heading: 'Claude does', text: 'The product-manager agent drafts <code>spec.md</code> with acceptance criteria. It never guesses a decision that is yours: it asks, with a suggested answer for each question.' },
      { heading: 'Claude asks, you answer', items: [
        'Resource path → <code>POST /tasks</code> and <code>GET /tasks</code>',
        'Maximum title length → 200 characters',
        'Surrounding whitespace → trimmed, a blank title is rejected',
        'Due date format → date only, <code>YYYY-MM-DD</code>',
        'Due dates in the past → accepted',
        'List order → oldest first',
        'Cap on tasks kept in memory → none',
        'Invalid requests → <code>422</code> in the standard validation format',
      ] },
      { heading: 'Result', text: '11 acceptance criteria (<code>AC-001.1</code> … <code>AC-001.11</code>), two of them smoke-tagged for the running service.' },
    ],
    links: [{ label: 'spec.md', href: `${SPEC}/spec.md` }],
  },
  {
    title: 'Approve the spec', short: 'Approve', say: 'Approve the spec', run: '/component:spec approve 001', command: 'Approve spec 001 now? → Approve', at: 115.0509, time: '',
    sections: [
      { heading: 'Claude does', text: 'Marks the spec approved, opens the spec PR and merges it once CI is green. Approval is the one decision the build waits for.' },
    ],
    links: [{ label: 'PR: the approved spec', href: `${API}/pull/2` }],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev', run: '/component:ship 001', command: '/component:ship 001', at: 126.412, time: '17 min',
    sections: [
      { heading: 'Claude does', items: [
        '<b>architect</b>: <code>design.md</code> and a plan of three tasks (schemas, in-memory store, endpoints), each covering named criteria.',
        '<b>tester</b>: acceptance tests for all 11 criteria, committed first and confirmed failing.',
        '<b>coders</b>: tasks 1 and 2 in parallel worktrees, then task 3, until the tests pass.',
        '<b>reviewer</b>: checks every criterion against tests and code and writes <code>verification.md</code>.',
        'Quality, tests and security gates, then the PR, merged after one green CI round.',
      ] },
      { heading: 'Result', text: '11 of 11 criteria met, 96 % coverage, PR merged; <code>main</code>\'s CI builds and publishes the image. The time includes PR and <code>main</code> CI (about 4 minutes).' },
    ],
    links: [
      { label: 'design.md', href: `${SPEC}/design.md` },
      { label: 'plan.md', href: `${SPEC}/plan.md` },
      { label: 'acceptance tests', href: `${API}/blob/main/tests/test_tasks.py` },
      { label: 'verification.md', href: `${SPEC}/verification.md` },
      { label: 'PR: the feature', href: `${API}/pull/3` },
    ],
  },
  {
    title: 'An escalation, as it happened', short: 'Escalation', say: 'Accept the formatter\'s change to the tests, it is formatting only', run: '/component:ship 001', command: '/component:ship 001 accept the lint-fix change, it is formatting only', at: 158.82, time: '',
    sections: [
      { heading: 'Why it stopped', text: 'The formatter rewrote the committed acceptance tests (<code>timezone.utc</code> → <code>UTC</code>). The build may not decide on its own that a changed test is harmless, so it stopped and asked. Accepting it resumed the run.' },
      { heading: 'Since then', text: 'Fixed: the tester formats the tests before committing them, so this stop no longer happens.' },
    ],
    links: [{ label: 'issue #367', href: `${ISSUES}/367` }],
  },
  {
    title: 'Deploy to dev', short: 'Deploy', say: '', run: '/component:ship 001 (continues)', command: '/component:ship 001 (deploy)', at: 185.972, time: '3 min',
    sections: [
      { heading: 'Claude does', items: [
        'The service\'s CI asks the gitops repo to pin dev to the new image; a pin PR opens and merges after its checks.',
        'Waits until Argo runs the new image, then runs the dev smoke tests for the smoke-tagged criteria.',
      ] },
      { heading: 'What went wrong', items: [
        `The pin PR waited for a manual approval of its checks, a GitHub rule for bot-opened PRs on public repos (<a href="${ISSUES}/368">#368</a>, fixed).`,
        `The dev smoke was skipped with "could not read the gitops-app" (<a href="${ISSUES}/369">#369</a>, fixed: retried and the error is named).`,
      ] },
      { heading: 'Result', text: 'Dev runs the new image, Argo Synced and Healthy.' },
    ],
    links: [{ label: 'PR: pin dev', href: `${GITOPS}/pull/4` }],
  },
  {
    title: 'Use it', short: 'Use it', say: 'Create a task with a due date in dev and list all tasks', run: 'curl -X POST $U/tasks … ; curl $U/tasks', command: 'curl -X POST $U/tasks … ; curl $U/tasks', at: 216.079, time: '< 1 min',
    sections: [
      { heading: 'Result', text: 'The new endpoint answers in dev: a task with a due date is created and listed next to one without.', code: '$ curl -s -X POST $U/tasks -H \'content-type: application/json\' \\\n    -d \'{"title": "Ship the demo", "due_date": "2026-11-10"}\'\n{"id":"3d6f8784-…","title":"Ship the demo","due_date":"2026-11-10",…}' },
    ],
    links: [{ label: 'the tasks endpoint', href: `${API}/blob/main/src/demo_taskboard_api/tasks_api.py` }],
  },
  // ---- part 2 (recorded 2026-11-04 with sdlc-foundry 5.7.0): a Postgres database and a web UI, one system spec ----
  {
    title: 'Add a web UI', short: 'Web UI', say: 'Add a web UI to the taskboard: a Next.js website in a public repo, part of this system',
    run: '/component:new demo-taskboard-web --type website · /component:add', command: 'Add a web UI to the taskboard: a Next.js website in a public repo, part of this system',
    at: 227.588, time: '7 min',
    sections: [
      { heading: 'Claude does', items: [
        'Picks <code>/component:new</code> from the sentence: a public Next.js repo from the <code>web-nextjs</code> template, <code>main</code> protected by its CI checks, linked to the gitops repo.',
        'Picks <code>/component:add</code> next: one PR that adds the web UI to <code>system.yaml</code>, exposed on the local Gateway, with <code>API_URL=http://demo-taskboard-api</code>.',
        'Merges that PR after its six checks pass.',
      ] },
      { heading: 'Your one manual step', text: 'A fine-grained token for the new repo (<code>GITOPS_TOKEN</code>, Contents read and write on the gitops repo), so dev follows its <code>main</code>. Claude prints the exact command; creating a token stays with you.' },
    ],
    links: [
      { label: 'demo-taskboard-web', href: WEB },
      { label: 'PR: add the web UI to system.yaml', href: `${GITOPS}/pull/7` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec', say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" → /system:spec approve 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    at: 254.529, time: '9 min',
    sections: [
      { heading: 'Claude does', text: 'In the gitops repo, the product-manager agent writes one system spec for all three repos. It asks before it decides anything that is yours, with a suggested answer each time.' },
      { heading: 'Claude asks, you answer', items: [
        'Replace the API\'s "a restart empties the list" criterion → yes',
        'Database unreachable → the API answers <code>503</code> and reports not ready',
        'One database per environment → yes',
        'The task list replaces the starter page → yes',
        'Texts, date format, no sign-in for now → as suggested',
        'Tasks kept in memory at the switch → dropped',
        'Backups → a separate spec, before the first prod release',
        'A cap on the list → none',
      ] },
      { heading: 'Result', text: '15 acceptance criteria across the API, the web UI and the gitops repo, published as a draft PR, approved and merged.' },
      { heading: 'What went wrong', text: 'Publishing had to wait for GitHub\'s API limit (5,000 points an hour per account), used up by two local consoles polling every 30 s. Stopping them fixed it.' },
    ],
    links: [
      { label: 'spec.md', href: `${SYS_SPEC}/spec.md` },
      { label: 'PR: the approved system spec', href: `${GITOPS}/pull/8` },
    ],
  },
  {
    title: 'Plan it across the repos', short: 'System plan', say: 'Plan it across the repos', run: '/system:plan 001', command: 'Plan it across the repos',
    at: 304.495, time: '4 min',
    sections: [
      { heading: 'Claude does', items: [
        'The planner assigns every criterion to a repo and orders them: the gitops repo first (declare Postgres, give the API its <code>DATABASE_URL</code>), then the API; the web UI in parallel.',
        'Writes the contract between them: the API keeps its fields and answers <code>503</code> with a fixed message when the database is down; the web UI calls it only from the server, with a 5 s timeout.',
        'Checks the plan (every criterion covered, no cycles) and merges it, so every agent builds from the reviewed version.',
      ] },
    ],
    links: [
      { label: 'the system plan', href: `${GITOPS}/blob/main/docs/plan/001-persistent-tasks-and-web-task-list.md` },
      { label: 'PR: spec and plan', href: `${GITOPS}/pull/9` },
    ],
  },
  {
    title: 'Ship it to dev', short: 'System ship', say: 'Merge the plan PR once its CI is green, then ship it to dev', run: '/system:ship 001',
    command: 'Merge the plan PR once its CI is green, then ship it to dev', at: 321.386, time: '≈ 30 min',
    sections: [
      { heading: 'Claude does', items: [
        '<b>gitops</b>: <code>/resource:add postgres</code> and <code>uses: [postgres]</code> on the API, one PR, merged on green CI.',
        '<b>web</b> and <b>API</b>, each through its own ship in parallel: a repo spec, a plan, failing acceptance tests first, code until they pass, review, PR, merge on green CI, pin to dev.',
        'The API replaces its in-memory store with Postgres (schema created under a lock), answers <code>503</code> and not-ready while the database is down, and recovers by itself.',
        'Finally <code>/instance:verify dev</code>: the smoke tests of both components pass against dev.',
      ] },
      { heading: 'What went wrong', items: [
        'Both PRs waited for GitHub\'s API limit once more before they could open.',
        'The web repo\'s first token could not write to the gitops repo, so its pin to dev failed with 403; a new token fixed it.',
        'The local cluster predated the new Postgres operator: one <code>devbox run bootstrap</code> by a person. The platform never applies to a cluster by itself.',
        `Resuming the web ship after the question in the next step lost the record of its merged PR, so its deploy check refused. The platform filed that as <a href="${ISSUES}/408">#408</a> by itself; dev was verified directly instead.`,
      ] },
      { heading: 'Result', text: 'Dev runs both new builds against a healthy Postgres; API smoke 4 of 4, web smoke 1 of 1. The web build itself took 16 minutes from its spec to done.' },
    ],
    links: [
      { label: 'PR: Postgres in system.yaml', href: `${GITOPS}/pull/10` },
      { label: 'PR: API on Postgres', href: `${API}/pull/6` },
      { label: 'PR: web task list', href: `${WEB}/pull/3` },
      { label: 'PR: pin API to dev', href: `${GITOPS}/pull/13` },
      { label: 'PR: pin web to dev', href: `${GITOPS}/pull/14` },
      { label: 'issue #408', href: `${ISSUES}/408` },
    ],
  },
  {
    title: 'A question only you can answer', short: 'Escalation', say: 'Yes, remove the starter content and keep the header and footer. Then continue the ship.',
    run: '/system:ship 001 (resumes)', command: 'Yes, remove the starter content and keep the header and footer. Then continue the ship.',
    at: 341.196, time: '',
    sections: [
      { heading: 'Why it stopped', text: 'The web repo\'s own spec had an open question: remove the template\'s starter content (hero, cards, "Get started") entirely and keep header and footer? The ship does not guess a decision that is yours, so it stopped and asked; the answer resumed it.' },
    ],
    links: [{ label: 'the web repo\'s spec', href: `${WEB}/blob/main/docs/specs/001-replace-the-starter-page-with-the-task/spec.md` }],
  },
  {
    title: 'Use it, and restart it', short: 'Use it', say: 'I just added a task in the web UI. Restart the API in dev and show that the task is still there.',
    run: 'browser · kubectl rollout restart · GET /tasks', command: 'I just added the task \'Ship part 2 of the demo\' in the web UI. Restart the API in dev and show that the task is still there.',
    at: 406.305, time: '2 min',
    sections: [
      { heading: 'In the browser', text: 'The task list replaces the starter page at <code>http://demo-taskboard-web.demo-taskboard-dev.localhost:8088</code>; a task added with the form appears at once.<img class="walkthrough-shot" src="/sdlc-foundry/img/demo/part2-web-ui.jpg" width="1200" height="784" loading="lazy" alt="The web UI in dev: the heading Tasks, two tasks (one from the smoke test, and Ship part 2 of the demo due 2026-11-10), and the form with Title, Due date and Add task." />' },
      { heading: 'Claude does', text: 'Leaves the restart to you: the demo repo\'s rules keep agents away from <code>kubectl</code>, so it prints the exact command. After the restart a new API pod returns the same task with the same <code>id</code> and <code>created_at</code>.' },
      { heading: 'Result', text: 'Tasks survive a restart. In part 1 the same restart emptied the list.' },
    ],
    links: [
      { label: 'the web UI\'s page', href: `${WEB}/blob/main/app/page.tsx` },
      { label: 'the Postgres store', href: `${API}/blob/main/src/demo_taskboard_api/task_store.py` },
    ],
  },
  // ---- part 3 (recorded 2026-11-04 with sdlc-foundry 5.7.0): staging, observability, releases, backups and prod ----
  {
    title: 'Staging and prod, with guard rails', short: 'Envs', say: 'Give staging and prod local hosts I can open in the browser, like dev, and enforce the guard rails in prod',
    run: '/system:set --env staging --host … · --env prod --host … --policy enforce', command: 'Give staging and prod local hosts I can open in the browser, like dev, and enforce the guard rails in prod',
    at: 420.977, time: '2 min',
    sections: [
      { heading: 'Claude does', text: 'Two <code>/system:set</code> PRs, one per environment: local hosts for staging and prod, and the Kyverno guard rails switched to <code>enforce</code> in prod, so a prod workload that breaks one fails its PR. Merged on green CI; the second one rebased onto the first.' },
    ],
    links: [
      { label: 'PR: prod host and enforce', href: `${GITOPS}/pull/16` },
      { label: 'PR: staging host', href: `${GITOPS}/pull/17` },
    ],
  },
  {
    title: 'Observability with one setting', short: 'Grafana', say: 'Turn on the Grafana observability stack for dev and staging, merge it once CI is green, then show me where to open Grafana',
    run: 'observability: {ui: lgtm} in system.yaml', command: 'Turn on the Grafana observability stack for dev and staging, merge it once CI is green, then show me where to open Grafana',
    at: 433.956, time: '4 min',
    sections: [
      { heading: 'Claude does', items: [
        'Sets <code>observability: {ui: lgtm}</code> for dev and staging in <code>system.yaml</code> (no command for it yet), renders: an OpenTelemetry collector per environment, <code>OTEL_*</code> variables for both components, and Grafana with traces, logs and metrics for the cluster.',
        'Leaves the one cluster change to you: <code>devbox run cluster-up</code> again adds the route to Grafana.',
      ] },
      { heading: 'Result', text: 'A minute of traffic later, Grafana shows the API\'s traces in dev: span rate, durations of 1–8 ms.<img class="walkthrough-shot" src="/sdlc-foundry/img/demo/part3-grafana-traces.jpg" width="1296" height="924" loading="lazy" alt="Grafana Traces Drilldown for the last 30 minutes: span rate up to 0.4 per second, span durations between 1 and 8 ms, no errors, 45 traces, all from the service demo-taskboard-api." />' },
    ],
    links: [{ label: 'PR: observability for dev and staging', href: `${GITOPS}/pull/18` }],
  },
  {
    title: 'Promote to staging', short: 'Staging', say: 'Promote the API and the web UI to staging and run their smoke tests there', run: '/instance:promote demo-taskboard-api demo-taskboard-web --to staging',
    command: 'Grafana shows the API\'s traces in dev. Now promote the API and the web UI to staging and run their smoke tests there.', at: 443.305, time: '6 min',
    sections: [
      { heading: 'Claude does', items: [
        'One PR pins the exact builds dev runs; staging gets its own Postgres and its own collector.',
        'The secrets scan flagged a configuration hash in a generated file; Claude checked it is not a secret and recorded it in the baseline.',
        'Runs the smoke tests against staging.',
      ] },
      { heading: 'Result', text: 'Staging runs both components on its own database: smoke API 4 of 4, web 1 of 1.' },
    ],
    links: [{ label: 'PR: promote to staging', href: `${GITOPS}/pull/19` }],
  },
  {
    title: 'Release what staging tested', short: 'Release', say: 'Release the API and the web UI from the builds staging tested, so they can go to prod', run: '/component:release (in both repos)',
    command: 'Release the API and the web UI from the builds staging tested, so they can go to prod', at: 455.529, time: '4 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos (API 68 tests, 96 % coverage; web 63 tests, 99 %).',
        'Tags exactly the commits staging tested (<code>v0.1.0</code>), so the release image is the tested image.',
      ] },
      { heading: 'Result', text: 'The API is released as <code>0.1.0</code>. The web UI is not: see the next step.' },
    ],
    links: [{ label: 'API v0.1.0', href: `${API}/tree/v0.1.0` }],
  },
  {
    title: 'The release gate stops a vulnerable build', short: 'Gate', say: 'Fix the web UI first so the release scan passes, take the fix through dev and staging, then release it as v0.1.1',
    run: '/component:fix → dev → staging → v0.1.1', command: 'Fix the web UI first: update its base image so the release scan passes, take the fix through dev and staging, then release it as v0.1.1',
    at: 463.209, time: '≈ 30 min',
    sections: [
      { heading: 'Why it stopped', text: 'The web release scan found four fixable HIGH/CRITICAL vulnerabilities in <code>undici</code> 6.28.0 inside the image (a certificate check bypass and three denial-of-service bugs). On <code>main</code> such findings are reported; a release stops on them.' },
      { heading: 'Claude does', items: [
        'Finds that a newer Node base image still ships the vulnerable <code>undici</code>, and removes <code>npm</code>, <code>npx</code> and <code>corepack</code>, which the app never uses, from the runtime image: 0 fixable findings, down from 5.',
        'Takes the fix through dev and staging like any change, then releases it as <code>0.1.1</code>.',
      ] },
      { heading: 'Result', text: 'API <code>0.1.0</code> and web <code>0.1.1</code>, each with the same image digest as staging.' },
    ],
    links: [
      { label: 'PR: the web fix', href: `${WEB}/pull/4` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/20` },
      { label: 'PR: fix to staging', href: `${GITOPS}/pull/21` },
      { label: 'web v0.1.1', href: `${WEB}/tree/v0.1.1` },
    ],
  },
  {
    title: 'Backups first, as the spec said', short: 'Backups', say: 'Before prod, as the spec decided: back up the prod database every night to a bucket in the cluster. Then promote both to prod.',
    run: '/system:spec → /system:plan 002 → /instance:promote … --to prod', command: 'Before prod, as the spec decided: back up the prod database every night to a bucket in the cluster. Then promote both to prod.',
    at: 504.567, time: '≈ 23 min',
    sections: [
      { heading: 'Claude does', text: 'Part 2\'s spec made backups a condition for the first prod release, so Claude writes spec 002 first and asks four questions.' },
      { heading: 'Claude asks, you answer', items: [
        'Backup time → 03:00 every night',
        'Retention → 30 days',
        'Other environments → prod only',
        'A restore drill before prod is used → yes',
      ] },
      { heading: 'The prod gate', text: 'The promotion check compares image digests (both match staging) and shows the evidence. It warned "no staging smoke record": the smoke tests had passed, but only <code>/component:ship</code> records them. The prod PR waited for a person\'s decision.' },
      { heading: 'What went wrong', items: [
        'Planning hit two platform limits: the plan check knows no bucket resource, and a bucket exists in prod only if a component uses it. The spec and the plan were adjusted and the gaps written down.',
      ] },
    ],
    links: [
      { label: 'spec 002', href: `${BACKUP_SPEC}/spec.md` },
      { label: 'PR: spec and plan', href: `${GITOPS}/pull/23` },
      { label: 'PR: prod with backups', href: `${GITOPS}/pull/24` },
    ],
  },
  {
    title: 'Prod, and a platform fix', short: 'Prod', say: 'I accept the warnings. Merge the prod PR, then run the restore drill.',
    run: 'merge #24 → /resource:backup → /resource:restore --to latest', command: 'I accept the two \'no staging smoke record\' warnings: staging smoke passed at 18:52 UTC on these exact builds. Before merging #24, fix the double External Secrets install: keep the one cluster-up installed, don\'t add a second. Then merge #24 once CI is green, run the restore drill and record its times.',
    at: 548.084, time: '≈ 40 min',
    sections: [
      { heading: 'Claude does', items: [
        'Removes a second External Secrets install from the prod PR, merges it on green CI: prod runs both components and a three-instance Postgres.',
        'Runs the restore drill: the first backup fails with <code>AccessDenied</code>.',
      ] },
      { heading: 'Why it failed', text: 'The database\'s WAL archiving created the bucket before the operator processed the platform\'s Bucket object, which then refused it ("already exists") and never granted access. A race in the platform.' },
      { heading: 'The fix', text: `The platform's renderer now adopts a bucket its database created first (<code>adoptExisting</code>), with a regression test; merged after 31 green checks, including the cluster e2e of backups. This fix was made in the platform repo by Claude Code outside the recorded terminal. <code>/platform:update</code> brought it into the system.` },
      { heading: 'Result', text: 'The prod bucket accepts backups; the drill backs up, restores into a separate copy and leaves prod unchanged.' },
    ],
    links: [
      { label: 'PR: platform fix', href: `${PLATFORM}/pull/412` },
      { label: 'PR: platform update', href: `${GITOPS}/pull/25` },
      { label: 'PR: restore drill', href: `${GITOPS}/pull/26` },
    ],
  },
  {
    title: 'Use it in prod, and restore it', short: 'Use prod', say: 'I just added the first task in prod. Back it up, restore it into a copy and show the task there.',
    run: 'browser · /resource:backup · /resource:restore --to latest · psql', command: 'I just added the first task in prod through the web UI. Prove that backups keep real data: show the task in prod, take a backup, restore it into a separate copy, show the same task in the copy, then discard the copy. Leave deleting the copies to me.',
    at: 611.068, time: '2 min',
    sections: [
      { heading: 'In the browser', text: 'The first task in prod, through the web UI at <code>http://demo-taskboard-web.demo-taskboard-prod.localhost:8088</code>.<img class="walkthrough-shot" src="/sdlc-foundry/img/demo/part3-prod-web-ui.jpg" width="1232" height="979" loading="lazy" alt="The web UI in prod: the heading Tasks, one task First task in prod due 2026-11-30, and the form with Title, Due date and Add task." />' },
      { heading: 'Claude does', text: 'Backs up, restores into a separate copy, and reads the copy: it holds the same task with the same title, due date and creation time. Deleting the copies stays with a person, because a discard deletes data.' },
      { heading: 'Result', text: 'Prod runs the exact images staging tested, behind enforced guard rails, with nightly backups that restore with their data.' },
    ],
    links: [{ label: 'PR: restore into a copy', href: `${GITOPS}/pull/28` }],
  },
];

/** The two recorded parts: the index of their first step and a heading. */
export const parts: { from: number; title: string; text: string }[] = [
  { from: 0, title: 'Part 1: from an empty folder to an endpoint in dev', text: 'One Python service, one spec, a local cluster.' },
  { from: 9, title: 'Part 2: a database and a web UI', text: 'One system spec across three repos: Postgres instead of memory, and a Next.js web UI.' },
  { from: 15, title: 'Part 3: operations', text: 'Guard rails, observability, staging, releases, backups and prod, with a restore drill.' },
];

/** The run at a glance (from the recording, the demo repos and docs/BASELINES.md). */
export const glance: { value: string; label: string }[] = [
  { value: '≈ 3 h 15', label: 'of work for all three parts, every wait cut' },
  { value: '3 envs', label: 'dev, staging and prod, each with its own Postgres' },
  { value: '1 build', label: 'stopped by the release scan before prod, then fixed' },
  { value: '1 drill', label: 'a prod backup restored into a copy, with its data' },
  { value: '31', label: 'real pull requests in the public demo repos' },
];
