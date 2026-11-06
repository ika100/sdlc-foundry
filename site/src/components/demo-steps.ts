// The steps of the recorded journey (journey 4, 2026-11-06, sdlc-foundry 5.11.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the journey record (`cplat platform runs journey`) and the demo repos.

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard4-gitops`;
const API = `${ORG}/taskboard4-api`;
const WEB = `${ORG}/taskboard4-web`;
const ISSUES = 'https://github.com/ika100/sdlc-foundry';

export interface Section { heading: string; text?: string; items?: string[]; code?: string }
export interface Step {
  title: string; short: string;
  /** what you would say in Claude Code; empty when the step needs no input */
  say: string;
  /** the command that runs (the plugin command Claude picks for `say`, or the shell command) */
  run: string;
  /** what was typed in the recording */
  command: string; at: number;
  /** working time of the step with the waits for people cut; CI rounds count */
  time: string;
  sections: Section[]; links: { label: string; href: string }[];
}

export const steps: Step[] = [
  {
    title: 'Create the system', short: 'System',
    say: 'Create a system named taskboard4 with one Python service, taskboard4-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard4.yaml --public', command: 'Create a system named taskboard4 with one Python service, taskboard4-api, …', at: 0, time: '2 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a four-line manifest, previews the run with <code>--dry-run</code>, then runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both, links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image. The organisation\'s <code>GITOPS_TOKEN</code> secret covers the service, so no token step is left for you.' },
    ],
    links: [
      { label: 'taskboard4-gitops', href: GITOPS },
      { label: 'taskboard4-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/1` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard4-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 7.453, time: '2 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and starts <code>devbox run cluster-up</code> in the background: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard4-api --expose</code> meanwhile: one PR with the route, merged on green CI.',
        'Ends its turn while the cluster still starts; the next step finds it up and the API Synced and Healthy in dev.',
      ] },
      { heading: 'Result', text: '<code>http://taskboard4-api.taskboard4-dev.localhost:8088/health</code> answers 200. Starting the cluster while the PR runs its CI saved most of the 6 minutes this step took in journey 3.' },
    ],
    links: [
      { label: 'PR: expose the API', href: `${GITOPS}/pull/2` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/3` },
    ],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard4-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/component:spec "create and list tasks …" · /component:spec approve 001', command: 'For taskboard4-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 16.524, time: '7 min',
    sections: [
      { heading: 'Claude does', text: 'A feature of one component takes the component route: the product-manager agent writes the spec in the API\'s own repo, with acceptance criteria, and asks every decision that is yours, each with a suggested answer. Then it asks for the approval and merges the spec PR on green CI.' },
      { heading: 'Claude asks, you answer', items: [
        'Due date in the past → accepted as given',
        'Limit on the number of tasks → none',
        'Title limit → 200 characters',
        'Whitespace → trimmed',
        'Invalid input → <code>422</code> naming the field',
        'List → a bare array, oldest first',
        'Fields → <code>id</code>, <code>title</code>, <code>due_date</code>',
        'Approve spec 001 → approve',
      ] },
      { heading: 'Result', text: '12 acceptance criteria, approved and merged, in the repo that builds them.' },
    ],
    links: [
      { label: 'the spec', href: `${API}/blob/main/docs/specs/001-create-and-list-tasks/spec.md` },
      { label: 'PR: the spec', href: `${API}/pull/2` },
    ],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/component:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 42.705, time: '21 min',
    sections: [
      { heading: 'Claude does', items: [
        'The architect plans the spec: t1 for the models, validation and in-memory store, t2 for the routes.',
        'The tester writes failing acceptance tests for all 12 criteria first, then the coders work until they pass; review, PR, merge on green CI after one round.',
        'Waits until dev runs the merged build and runs the smoke tests against it.',
      ] },
      { heading: 'What went wrong', items: [
        `Once the task package existed, <code>lint-fix</code> moved one import line in the acceptance tests. No assertion changed, but a changed acceptance test needs a person's OK, so the ship stopped; the OK took 20 seconds (<a href="${ISSUES}/issues/519">#519</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs the task API; <code>POST /tasks</code> and <code>GET /tasks</code> answer, smoke 5 of 5. 21 minutes instead of 55 in journey 3: no stop-hook pause, no conflicting branch, no stale lint cache.' },
    ],
    links: [
      { label: 'PR: the task API', href: `${API}/pull/3` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/4` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard4-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard4-web --system ika100-demo/taskboard4-gitops … · /component:add taskboard4-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard4-web …', at: 83.703, time: '7 min',
    sections: [
      { heading: 'Claude does', text: 'Creates the Next.js repo from its template in the system\'s organisation, adds it to <code>system.yaml</code> with its own host in dev, merges that PR on green CI and waits until dev runs it.' },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard4-web.taskboard4-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard4-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/5` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/6` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 100.823, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'This feature spans three repos, so it takes the system route: one system spec in the gitops repo. The API moves to Postgres, the web UI lists tasks and creates them with a form.' },
      { heading: 'Claude asks, you answer', items: [
        'Database down → the API answers <code>503</code> within 10 seconds and reports not ready',
        'API instances in dev → two, so the shared storage gets exercised',
        'Backups → a later spec',
        'List order → oldest first',
        'Due date in the web UI → <code>2026-12-31</code>',
        'Titles → shown as written; the field stops at 200 characters',
        'Where → the root page',
        'Approve system spec 001 → approve',
      ] },
      { heading: 'Result', text: '12 criteria, approved and merged on the first spec check.' },
    ],
    links: [
      { label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-in-postgres-with-a-web/spec.md` },
      { label: 'PR: the spec', href: `${GITOPS}/pull/7` },
    ],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 001 · /system:ship 001', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 124.426, time: '65 min',
    sections: [
      { heading: 'Claude does', items: [
        '<b>gitops</b>: Postgres, two API instances in dev and the API address for the web UI; one PR that waits until both builds are done.',
        '<b>API</b> (19 criteria) and <b>web</b> (23 criteria), each through its own ship in parallel: a repo spec, a plan, failing acceptance tests first, code, review, PR, merge on green CI. The web spec\'s five questions took the suggested answers.',
        'The API first retires the in-memory criterion "tasks are gone after a restart" of its first spec, in its own PR; only that one test goes.',
        'Lands the gitops PR, installs the CloudNativePG operator, waits until dev runs both builds, smoke.',
      ] },
      { heading: 'What went wrong', items: [
        `The template's metrics smoke test counts a request on one instance and reads <code>/metrics</code> once; with two instances the read can reach the other one, so the dev smoke went red. Claude fixed the test to read until it reaches the instance that counted the request (<a href="${ISSUES}/issues/520">#520</a>).`,
        `The fix changed only a test, so the image stayed the same, and the ship could not record the green smoke: it tried to pin the build dev already ran (<a href="${ISSUES}/issues/521">#521</a>). Claude closed the spec by hand with <code>/system:spec done</code>.`,
        `Installing the operator meant running <code>devbox run bootstrap</code>, which the gitops repo reserves for a person (<a href="${ISSUES}/issues/522">#522</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres, shared by two API instances; API smoke 5 of 5, web smoke 4 of 4. Two stops, answered with the recommended option; 65 minutes instead of 89.' },
    ],
    links: [
      { label: 'PR: the plan', href: `${GITOPS}/pull/8` },
      { label: 'PR: Postgres and wiring', href: `${GITOPS}/pull/9` },
      { label: 'PR: API on Postgres', href: `${API}/pull/5` },
      { label: 'PR: the web task list', href: `${WEB}/pull/3` },
      { label: 'PR: the smoke test fix', href: `${API}/pull/7` },
      { label: 'PR: spec done', href: `${GITOPS}/pull/11` },
    ],
  },
  {
    title: 'Hosts, observability and staging', short: 'Staging',
    say: 'Give staging and prod local hosts I can open in the browser, turn on the Grafana observability stack for dev and staging, and promote both components to staging. Merge the PRs once their CI is green.',
    run: '/system:set --host · observability · /instance:promote --to staging --smoke', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 192.777, time: '13 min',
    sections: [
      { heading: 'Claude does', text: 'Sets a host for staging and prod, turns on the Grafana stack (logs, metrics, traces) for dev and staging, and promotes the builds dev tested to staging, both components in one PR. The promotion runs the staging smoke itself (since 5.11.0), so the prod check has its record. Four PRs, each merged on green CI.' },
      { heading: 'What went wrong', items: [
        `The Grafana stack's operator reached the cluster only through another <code>devbox run bootstrap</code> (<a href="${ISSUES}/issues/522">#522</a>).`,
      ] },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; smoke 3 of 3 for each, all 12 apps Synced and Healthy, Grafana at <code>http://grafana.localhost:8088</code>. 13 minutes instead of 32.' },
    ],
    links: [
      { label: 'PR: staging host', href: `${GITOPS}/pull/12` },
      { label: 'PR: observability', href: `${GITOPS}/pull/14` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/15` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo)', command: 'Release the API and the web UI from the builds staging tested', at: 221.544, time: '13 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos, then tags <code>v0.1.0</code> on the commit staging runs: the tag never rebuilds, it gives the tested image its version.',
        'A follow-up PR per repo adds the changelog and moves <code>main</code> to the next development version.',
      ] },
      { heading: 'Result', text: 'Both releases point at exactly the images staging tested. The image scans find HIGH findings in the Debian base images\' OS packages, none in the Python or Node packages; they report, they do not block.' },
    ],
    links: [
      { label: 'PR: API follow-up', href: `${API}/pull/8` },
      { label: 'PR: web follow-up', href: `${WEB}/pull/4` },
    ],
  },
  {
    title: 'Backups and the prod PR', short: 'Prod PR',
    say: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR for both components, but don\'t merge it.',
    run: '/resource:add backups --type bucket · /instance:promote --all --to prod', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 243.587, time: '9 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups: a daily backup of the prod database at 03:00 UTC, kept 30 days.',
        'Opens one prod PR for both components at 0.1.0 (since 5.11.0), with Postgres at three instances.',
      ] },
      { heading: 'The prod check', text: `Before anything reaches prod the promotion shows its evidence: the image digests match what staging tested, staging smoke passed, no open smoke-failure or alert issue, CI green, no warning. The API's dev smoke has no record for the release commit, because its follow-up had already moved dev on (<a href="${ISSUES}/issues/523">#523</a>).` },
    ],
    links: [
      { label: 'PR: backups bucket', href: `${GITOPS}/pull/17` },
      { label: 'PR: both to prod', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', run: 'merge the prod PR · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', at: 271.255, time: '8 min',
    sections: [
      { heading: 'Claude does', text: 'Merges the prod PR on green CI, waits for Argo, runs the smoke tests against prod and creates the "Prod check" task through the prod API.' },
      { heading: 'What went wrong', items: [
        `The new SeaweedFS operator reached the cluster only through another <code>devbox run bootstrap</code> (<a href="${ISSUES}/issues/522">#522</a>).`,
      ] },
      { heading: 'Result', text: 'Prod runs both components at 0.1.0; smoke 3 of 3 for each (the API\'s two writing tests run only in dev), Postgres 3 of 3 ready, and the first backup ran when the schedule was created.' },
    ],
    links: [
      { label: 'PR: both to prod', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:restore postgres --env prod --to latest · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 291.126, time: '13 min',
    sections: [
      { heading: 'Claude does', items: [
        'Restores the prod database from its backups to a separate copy next to the running one; prod keeps serving.',
        'Queries the copy read-only: the "Prod check" task is there, with the id the prod API gave it. Then discards the copy and its volumes with <code>--confirm prod</code>.',
      ] },
      { heading: 'Result', text: 'A checked restore on the first try, without touching prod and without a manual backup. <code>--switch</code> would make the copy the active database in a real recovery.' },
    ],
    links: [
      { label: 'PR: restore', href: `${GITOPS}/pull/20` },
      { label: 'PR: discard', href: `${GITOPS}/pull/21` },
    ],
  },
];

/** The three recorded parts: the index of their first step and a heading. */
export const parts: { from: number; title: string; text: string }[] = [
  { from: 0, title: 'Part 1: from an empty folder to an endpoint in dev', text: 'One Python service, one spec in its own repo, a local cluster.' },
  { from: 4, title: 'Part 2: a database and a web UI', text: 'One system spec across three repos: Postgres instead of memory, and a Next.js web UI.' },
  { from: 7, title: 'Part 3: staging, a release, prod and a restore', text: 'Hosts, observability, a release from the tested builds, prod with daily backups, and a restore drill.' },
];

/** The run at a glance (from the recording, the journey record and the demo repos). */
export const glance: { value: string; label: string }[] = [
  { value: '≈ 2 h 45', label: 'of work from an empty folder to a checked restore, CI rounds included' },
  { value: '2 min', label: 'of a person\'s time: 19 answers, 3 stops on a platform problem' },
  { value: '3 repos', label: 'API, web UI and gitops, from an empty folder to prod' },
  { value: '29', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
