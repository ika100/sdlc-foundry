// The steps of the recorded journey (journey 6, 2026-11-07, sdlc-foundry 5.13.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the journey record (`cplat platform runs journey`) and the demo repos.

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard6-gitops`;
const API = `${ORG}/taskboard6-api`;
const WEB = `${ORG}/taskboard6-web`;
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
    say: 'Create a system named taskboard6 with one Python service, taskboard6-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard6.yaml --public', command: 'Create a system named taskboard6 with one Python service, taskboard6-api, …', at: 0, time: '3 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a short manifest, previews the run with <code>--dry-run</code>, then runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both, links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'What the platform handled', text: `A GitHub call timed out on the way; since 5.13.0 every GitHub and git call that never reached GitHub runs again by itself (spec 148), so the step finished without a stop. In journey 5 the same drop cost two resumes.` },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image, and one PR that adds the service to the system.' },
    ],
    links: [
      { label: 'taskboard6-gitops', href: GITOPS },
      { label: 'taskboard6-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/1` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard6-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 10.626, time: '7 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and runs <code>devbox run cluster-up</code>: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard6-api --expose</code>: one PR with the route, merged on green CI.',
        'Waits with <code>cplat system wait --env dev</code>, which asks Argo CD for one refresh when an app is still behind (spec 148), until the app is Synced and Healthy.',
      ] },
      { heading: 'Result', text: '<code>http://taskboard6-api.taskboard6-dev.localhost:8088/health</code> answers 200.' },
    ],
    links: [
      { label: 'PR: pin dev', href: `${GITOPS}/pull/2` },
      { label: 'PR: expose the API', href: `${GITOPS}/pull/3` },
    ],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard6-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/component:spec "create and list tasks …" · /component:spec approve 001', command: 'For taskboard6-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 25.643, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'A feature of one component takes the component route. New in 5.13.0 (spec 149): the product-manager agent decides every default itself and lists it under <b>Assumptions</b>; it asks only what it may not decide (security, money, data, or a request too ambiguous to build). You approve the spec together with its assumptions in one question.' },
      { heading: 'Claude asks, you answer', items: [
        'May anyone who can reach the API create and list tasks, without authentication? → yes, for now',
        'Approve spec 001 with these 6 assumptions → approve',
      ] },
      { heading: 'Assumptions approved with the spec', items: [
        '<code>POST /tasks</code> and <code>GET /tasks</code> with the fields <code>id</code>, <code>title</code>, <code>due_date</code>, <code>created_at</code>',
        'A due date is a calendar date; past dates are allowed',
        'A title is 1 to 200 characters after trimming',
        'Validation errors answer <code>422</code>; ids are server-made UUIDs',
        'The list returns every task, oldest first',
      ] },
      { heading: 'Result', text: '7 acceptance criteria, approved and merged in the repo that builds them, after 2 questions instead of 11.' },
    ],
    links: [
      { label: 'the spec', href: `${API}/blob/main/docs/specs/001-create-and-list-tasks/spec.md` },
      { label: 'PR: the spec', href: `${API}/pull/2` },
    ],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/component:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 42.646, time: '21 min',
    sections: [
      { heading: 'Claude does', items: [
        'The architect plans 2 tasks; the tester writes failing acceptance tests for all 7 criteria first, then the coders work until they pass.',
        'Review against the spec, then a mutation check (spec 152): small faults are put into the new code one at a time; the acceptance tests caught 16 of 17.',
        'One PR, merged after one CI round; waits until dev runs the merged build and runs the smoke tests against it.',
      ] },
      { heading: 'Result', text: 'Dev runs the task API; <code>POST /tasks</code> and <code>GET /tasks</code> answer, smoke 4 of 4. No stop; 21 minutes instead of 33 (+ 65 blocked) in journey 5.' },
    ],
    links: [
      { label: 'PR: the task API', href: `${API}/pull/3` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/4` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard6-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard6-web --system ika100-demo/taskboard6-gitops … · /component:add taskboard6-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard6-web …', at: 72.483, time: '13 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 2 (<code>/clear</code>): every command keeps its state in the repos. Claude creates the Next.js repo from its template, adds it to <code>system.yaml</code> with its own host in dev, merges that PR on green CI and waits until dev runs it.' },
      { heading: 'What went wrong', items: [
        'The first wait timed out: it still looked for the image of the add PR while the automatic pin PR had already moved dev to the first build. The second wait was ready.',
      ] },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard6-web.taskboard6-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard6-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/5` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/6` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 97.1, time: '4 min',
    sections: [
      { heading: 'Claude does', text: 'This feature spans three repos, so it takes the system route: one system spec in the gitops repo. The API moves to Postgres, the web UI lists tasks and adds them with a form.' },
      { heading: 'Claude asks, you answer', items: [
        'Approve system spec 001 with these 9 assumptions → approve',
      ] },
      { heading: 'Assumptions approved with the spec', items: [
        'The API contract stays unchanged; tasks held in memory are not migrated',
        'Without the database the API answers <code>503</code> and reports not ready',
        'One page at the web root: the form above the list, oldest task first, dates as <code>YYYY-MM-DD</code>',
        'The form checks the title limits and shows the API\'s error too; texts in English',
        'The database is the system\'s own Postgres in the cluster, no paid service',
      ] },
      { heading: 'Result', text: '8 criteria, approved and merged with one question instead of seven.' },
    ],
    links: [
      { label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-and-task-ui/spec.md` },
      { label: 'PR: the spec', href: `${GITOPS}/pull/7` },
    ],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 001 · /system:ship 001', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 108.007, time: '51 min',
    sections: [
      { heading: 'Claude does', items: [
        'The planner splits the 8 criteria across the repos and writes each component repo\'s own criteria into the plan (spec 147): 7 for the API, 14 for the web UI.',
        'Each repo spec is created from the plan and approved at once: no product-manager round and no questions per repo.',
        '<b>API</b> and <b>web</b> build in parallel: a repo plan, failing acceptance tests first, code, review, a mutation check (API: 13 of 20 faults caught), PR, merge on green CI.',
        '<b>gitops</b>: Postgres for the API and the API address for the web UI, landed with both builds in one PR after green checks.',
      ] },
      { heading: 'Why it took longer than in journey 5', items: [
        'The web repo spec came out at 14 criteria (the planner aims at 3 to 8), and the API build\'s coders ran one after the other instead of in parallel. The ship itself needed no stop and no re-wait.',
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres; API smoke 4 of 4, web smoke 3 of 3.' },
    ],
    links: [
      { label: 'PR: spec and plan', href: `${GITOPS}/pull/8` },
      { label: 'PR: API on Postgres', href: `${API}/pull/4` },
      { label: 'PR: the web task board', href: `${WEB}/pull/3` },
      { label: 'PR: Postgres and wiring', href: `${GITOPS}/pull/9` },
      { label: 'PR: spec done', href: `${GITOPS}/pull/10` },
    ],
  },
  {
    title: 'Hosts, observability and staging', short: 'Staging',
    say: 'Give staging and prod local hosts I can open in the browser, turn on the Grafana observability stack for dev and staging, and promote both components to staging. Merge the PRs once their CI is green.',
    run: '/system:set --host · observability · /instance:promote --to staging --smoke', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 150.723, time: '14 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 3. Claude sets a host for staging and prod, turns on the Grafana stack (logs, metrics, traces) for dev and staging, and promotes the builds dev tested to staging in one PR, which runs the staging smoke itself. Four PRs, each merged on green CI.' },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; smoke green, Grafana at <code>http://grafana.localhost:8088</code>.' },
    ],
    links: [
      { label: 'PR: staging host', href: `${GITOPS}/pull/11` },
      { label: 'PR: observability', href: `${GITOPS}/pull/13` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/14` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo)', command: 'Release the API and the web UI from the builds staging tested', at: 179.155, time: '10 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos, then tags <code>v0.1.0</code> on the commit staging runs: the tag never rebuilds, it gives the tested image its version.',
        'The security gate now names the audit tool each repo runs and scans the container images (#545): only base-image findings without a fix, reported, not a stop.',
        'A follow-up PR per repo adds the changelog and moves <code>main</code> to the next development version.',
      ] },
      { heading: 'Result', text: 'Both releases point at exactly the images staging tested.' },
    ],
    links: [
      { label: 'PR: API follow-up', href: `${API}/pull/5` },
      { label: 'PR: web follow-up', href: `${WEB}/pull/4` },
    ],
  },
  {
    title: 'Backups and the prod PR', short: 'Prod PR',
    say: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR for both components, but don\'t merge it.',
    run: '/resource:add backups --type bucket · /instance:promote --all --to prod', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 197.858, time: '7 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups: a daily backup of the prod database at 03:00 UTC, kept 30 days, and merges that PR first, because the prod PR is built from <code>main</code> (it says so in its answer).',
        'Opens one prod PR for both components at 0.1.0, with Postgres at three instances.',
      ] },
      { heading: 'The prod check', text: 'The promotion shows its evidence before anything reaches prod: the image digests match what staging tested, dev and staging smoke passed for both components, no open smoke-failure or alert issue, CI green, no warning.' },
    ],
    links: [
      { label: 'PR: backups', href: `${GITOPS}/pull/15` },
      { label: 'PR: both to prod', href: `${GITOPS}/pull/18` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', run: 'merge the prod PR · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', at: 214.242, time: '13 min',
    sections: [
      { heading: 'Claude does', text: 'Merges the prod PR on green CI, waits for Argo (the new three-instance Postgres took a second wait), runs the smoke tests against prod and creates the "Prod check" task through the prod API.' },
      { heading: 'Result', text: 'Prod runs both components at 0.1.0; all 4 prod apps Synced and Healthy, smoke green (the API\'s writing test runs only in dev), and the "Prod check" task is the only task in prod.' },
    ],
    links: [
      { label: 'PR: both to prod', href: `${GITOPS}/pull/18` },
    ],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:backup postgres --env prod · /resource:restore postgres --env prod --to latest · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 240.316, time: '16 min',
    sections: [
      { heading: 'Claude does', items: [
        'The first restore was refused: the only backup had finished a minute before the "Prod check" task was created. Claude took an on-demand backup.',
        'Restores the prod database from it to a separate copy next to the running one; prod keeps serving.',
        'Queries the copy read-only: the "Prod check" task is there, with the id the prod API gave it. Then discards the copy and its volumes with <code>--confirm prod</code>.',
      ] },
      { heading: 'Result', text: 'A checked restore without touching prod. <code>--switch</code> would make the copy the active database in a real recovery.' },
    ],
    links: [
      { label: 'PR: restore', href: `${GITOPS}/pull/19` },
      { label: 'PR: discard', href: `${GITOPS}/pull/20` },
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
  { value: '≈ 2 h 45', label: 'from an empty folder to a checked restore, CI rounds included, without a single stop' },
  { value: '40 M', label: 'tokens, 13 % fewer than journey 5' },
  { value: '3', label: 'questions in the whole run (20 in journey 5): the specs decide their defaults and show them at approval' },
  { value: '26', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
