// The steps of the recorded journey (journey 11, 2026-11-12, sdlc-foundry 5.18.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the journey record (`cplat platform runs journey`) and the demo repos.

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard11-gitops`;
const API = `${ORG}/taskboard11-api`;
const WEB = `${ORG}/taskboard11-web`;
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
    say: 'Create a system named taskboard11 with one Python service, taskboard11-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard11.yaml --public', command: 'Create a system named taskboard11 with one Python service, taskboard11-api, …', at: 0.0, time: '1.5 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a short manifest and runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both (quality, tests, security scans must pass), links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image, and one PR that adds the service to the system.' },
    ],
    links: [
      { label: 'taskboard11-gitops', href: GITOPS },
      { label: 'taskboard11-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/1` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard11-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 7.594, time: '5 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and runs <code>devbox run cluster-up</code>: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard11-api --expose</code>: one PR with the route, merged after its 6 checks passed.',
        'Waits with <code>cplat system wait --env dev</code> until the app is Synced and Healthy.',
      ] },
      { heading: 'Result', text: '<code>http://taskboard11-api.taskboard11-dev.localhost:8088/docs</code> and <code>/health</code> answer 200.' },
    ],
    links: [
      { label: 'PR: expose the API', href: `${GITOPS}/pull/3` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/4` },
    ],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard11-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/component:spec "create and list tasks …" · /component:spec approve 001', command: 'For taskboard11-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 22.837, time: '4 min',
    sections: [
      { heading: 'Claude does', text: 'A feature of one component takes the component route. The product-manager agent decides every default itself and lists it under <b>Assumptions</b>; it asks only what it may not decide. You approve the spec together with its assumptions in one question.' },
      { heading: 'Claude asks, you answer', items: [
        'Approve spec 001 with these 8 assumptions → approve',
      ] },
      { heading: 'Result', text: '7 acceptance criteria and 8 assumptions, approved and merged in the repo that builds them, after one question.' },
    ],
    links: [
      { label: 'the spec', href: `${API}/blob/main/docs/specs/001-create-and-list-tasks-in-memory/spec.md` },
      { label: 'PR: the spec', href: `${API}/pull/3` },
    ],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/component:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 36.872, time: '17 min',
    sections: [
      { heading: 'Claude does', items: [
        'The architect plans the tasks; the tester writes failing acceptance tests for all 7 criteria first, then the coders work until they pass.',
        'Review against the spec, then a mutation check: small faults are put into the new code one at a time; the acceptance tests caught 15 of 16.',
        'One PR, merged on green CI; waits until dev runs the merged build and runs the smoke tests against it.',
      ] },
      { heading: 'Result', text: 'Dev runs the task API; <code>POST /tasks</code> and <code>GET /tasks</code> answer, smoke 6 of 6. No question and no stop.' },
    ],
    links: [
      { label: 'PR: the task API', href: `${API}/pull/4` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/5` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard11-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard11-web --system ika100-demo/taskboard11-gitops … · /component:add taskboard11-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard11-web …', at: 66.631, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 2 (<code>/clear</code>): every command keeps its state in the repos. Claude creates the Next.js repo from its template, adds it to <code>system.yaml</code> with its own host in dev, merges that PR on green CI and waits until dev runs it.' },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard11-web.taskboard11-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard11-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/6` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/7` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 83.006, time: '5 min',
    sections: [
      { heading: 'Claude does', text: 'This feature spans three repos, so it takes the system route: one system spec in the gitops repo. The API moves to Postgres, the web UI lists tasks and adds them with a form.' },
      { heading: 'Claude asks, you answer', items: [
        'May people use the app without a login? → yes, for dev (the suggested answer; one the product manager may not decide itself)',
        'Approve system spec 001 → approve',
      ] },
      { heading: 'Result', text: 'The system spec "Persistent tasks with web UI", approved and merged after two questions.' },
    ],
    links: [
      { label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-with-web-ui/spec.md` },
      { label: 'PR: the spec', href: `${GITOPS}/pull/8` },
    ],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 001 · /system:ship 001', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 98.314, time: '48 min',
    sections: [
      { heading: 'Claude does', items: [
        'The planner splits the spec across the three repos and writes each component repo\'s criteria into the plan; each repo spec is created from it and approved at once, so no repo asked a question.',
        '<b>API</b> and <b>web</b> build in parallel, each in its own session: a repo plan, failing acceptance tests first, code, review, a mutation check, PR, merge on green CI.',
        '<b>gitops</b>: Postgres for the API and the API address for the web UI, in one PR kept open until both builds were in, so dev changed once. The landing step installed the database operator on the local cluster itself.',
      ] },
      { heading: 'The one stop', items: [
        `The API's plan required one task to pass before the next one existed: its tests load the app, which still used the in-memory store until the following task. The ship paused for a person instead of changing a repo's plan; the answer "merge t2 into t3" let it go on (<a href="${ISSUES}/issues/681">#681</a>: the plan check should catch this).`,
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres; API and web smoke green. Every PR passed CI on its first round.' },
    ],
    links: [
      { label: 'PR: spec and plan', href: `${GITOPS}/pull/9` },
      { label: 'PR: API on Postgres', href: `${API}/pull/5` },
      { label: 'PR: the task page', href: `${WEB}/pull/4` },
      { label: 'PR: Postgres and wiring', href: `${GITOPS}/pull/10` },
      { label: 'PR: spec done', href: `${GITOPS}/pull/11` },
    ],
  },
  {
    title: 'Hosts, observability and staging', short: 'Staging',
    say: 'Give staging and prod local hosts I can open in the browser, turn on the Grafana observability stack for dev and staging, and promote both components to staging. Merge the PRs once their CI is green.',
    run: '/system:set --host · observability · /instance:promote --to staging --smoke', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 185.785, time: '9 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 3. Claude sets a host for staging and prod, turns on the Grafana stack (logs, metrics, traces) for dev and staging, and promotes the builds dev tested to staging in one PR, which runs the staging smoke itself.' },
      { heading: 'What went wrong', items: [
        `The observability PR failed its secrets scan: the log tailer added in 5.18.0 writes a <code>checksum/tailer</code> annotation that the scan read as a secret. Fixed in 5.19.0 (<a href="${ISSUES}/issues/678">#678</a>); after the run, the gitops repo took the update and the PR merged.`,
      ] },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; smoke green (API 4 passed, 2 writing tests only run in dev; web 1 of 1).' },
    ],
    links: [
      { label: 'PR: staging host', href: `${GITOPS}/pull/12` },
      { label: 'PR: prod host', href: `${GITOPS}/pull/13` },
      { label: 'PR: observability', href: `${GITOPS}/pull/14` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/15` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo)', command: 'Release the API and the web UI from the builds staging tested', at: 205.585, time: '8 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos side by side, then tags <code>v0.1.0</code> on the commit staging runs: CI gives the tested image its version without rebuilding it.',
        `The image scan reports base-image findings without a fix (not a stop): the web image's Debian 12 base carries one critical zlib CVE (<a href="${ISSUES}/issues/682">#682</a>).`,
        'A follow-up PR per repo adds the changelog and moves <code>main</code> to the next development version.',
      ] },
      { heading: 'Result', text: 'Both releases point at exactly the images staging tested.' },
    ],
    links: [
      { label: 'PR: API follow-up', href: `${API}/pull/6` },
      { label: 'PR: web follow-up', href: `${WEB}/pull/5` },
    ],
  },
  {
    title: 'Backups and the prod PR', short: 'Prod PR',
    say: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR for both components, but don\'t merge it.',
    run: '/resource:add backups --type bucket · /instance:promote --all --to prod', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 222.399, time: '6 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups and a daily backup of the prod database, which also takes one backup right away, and merges that PR first.',
        'Opens one prod PR for both components at 0.1.0, with Postgres at three instances.',
      ] },
      { heading: 'The prod check', text: 'The promotion shows its evidence before anything reaches prod: the image digests match what staging tested, dev and staging smoke passed for both components, and no smoke-failure or alert issue is open.' },
    ],
    links: [
      { label: 'PR: backups', href: `${GITOPS}/pull/16` },
      { label: 'PR: both to prod', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', run: 'merge the prod PR · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', at: 237.127, time: '7 min',
    sections: [
      { heading: 'Claude does', text: 'Merges the prod PR on green CI, waits for Argo, runs the smoke tests against prod and creates the "Prod check" task through the prod API.' },
      { heading: 'Result', text: 'Prod runs both components at 0.1.0; all four prod apps Healthy, smoke green (the API\'s writing tests run only in dev), and the "Prod check" task is the only task in prod.' },
    ],
    links: [
      { label: 'PR: both to prod', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:restore postgres --env prod --to latest · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 249.201, time: '14 min',
    sections: [
      { heading: 'Claude does', items: [
        'Restores the prod database to the latest point as a separate copy next to the running one, through a gitops PR; prod keeps serving. The task was created after the first full backup, so the restore also replayed the database\'s change log.',
        `Queries the copy read-only: the "Prod check" task is there, with the id the prod API gave it. No command runs that check yet, so it used <code>kubectl</code> once (<a href="${ISSUES}/issues/683">#683</a>).`,
        'Discards the copy and its volumes with <code>--confirm prod</code>, through a second PR.',
      ] },
      { heading: 'Result', text: 'A checked restore without touching prod. <code>--switch</code> would make the copy the active database in a real recovery.' },
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
  { value: '≈ 2 h 10', label: 'from an empty folder to a checked restore, CI rounds included' },
  { value: '35 M', label: 'tokens' },
  { value: '3', label: 'questions in the whole run, all answered with the suggested option; one stop for a plan decision' },
  { value: '26', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
