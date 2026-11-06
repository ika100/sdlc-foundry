// The steps of the recorded journey (journey 3, 2026-11-05/06, sdlc-foundry 5.10.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the journey record (`cplat platform runs journey`) and the demo repos.

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard3-gitops`;
const API = `${ORG}/taskboard3-api`;
const WEB = `${ORG}/taskboard3-web`;
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
    say: 'Create a system named taskboard3 with one Python service, taskboard3-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard3.yaml --public', command: 'Create a system named taskboard3 with one Python service, taskboard3-api, …', at: 0, time: '2 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a four-line manifest, previews the run with <code>--dry-run</code>, then runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both, links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image. The organisation\'s <code>GITOPS_TOKEN</code> secret covers the service, so no token step is left for you.' },
    ],
    links: [
      { label: 'taskboard3-gitops', href: GITOPS },
      { label: 'taskboard3-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/1` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard3-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 8.468, time: '6 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and runs <code>devbox run cluster-up</code>: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard3-api --expose</code>: one PR with the route, merged on green CI.',
        'Waits with <code>cplat system wait --env dev</code> until Argo reports the app Synced and Healthy on the merged commit.',
      ] },
      { heading: 'Result', text: '<code>http://taskboard3-api.taskboard3-dev.localhost:8088/health</code> answers 200. Journey 2 needed 15 minutes here; the platform\'s own waits (spec 143) replaced hand-written polling.' },
    ],
    links: [
      { label: 'PR: expose the API', href: `${GITOPS}/pull/2` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/3` },
    ],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard3-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/component:spec "create and list tasks …" (in taskboard3-api)', command: 'For taskboard3-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 23.865, time: '5 min',
    sections: [
      { heading: 'Claude does', text: 'A feature of one component takes the component route: the product-manager agent writes the spec in the API\'s own repo, with acceptance criteria, and asks every decision that is yours, each with a suggested answer.' },
      { heading: 'Claude asks, you answer', items: [
        'Title limit → 200 characters',
        'Whitespace → trimmed; a title of only spaces is rejected',
        'Due date in the past → accepted unchanged',
        'Limit on the number of tasks → none in this spec',
        'Paths and fields → <code>/tasks</code> with <code>id</code>, <code>title</code>, <code>due_date</code>',
        '<code>created_at</code> in responses → not in this spec',
      ] },
      { heading: 'Result', text: '13 acceptance criteria, in the repo that builds them. No system spec and no system plan are needed for one component.' },
    ],
    links: [{ label: 'the spec', href: `${API}/blob/main/docs/specs/001-create-and-list-tasks-in-memory/spec.md` }],
  },
  {
    title: 'Approve the spec', short: 'Approve', say: 'Approve the spec', run: '/component:spec approve 001', command: '(Approve, the recommended answer)', at: 36.372, time: '2 min',
    sections: [
      { heading: 'Claude does', text: 'Marks the spec approved and merges its PR on green CI. Nothing is built from a draft.' },
    ],
    links: [{ label: 'PR: the spec', href: `${API}/pull/2` }],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/component:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 44.754, time: '55 min',
    sections: [
      { heading: 'Claude does', items: [
        'The architect plans the spec (2 tasks, 2 minutes).',
        'The tester writes failing acceptance tests for all 13 criteria first, then the coder works until they pass; review, PR, merge on green CI (28 minutes of build, 15 of PR and CI).',
        'Waits until dev runs the merged build and runs the smoke tests against it (9 minutes).',
      ] },
      { heading: 'What went wrong', items: [
        `The coordinator ended two turns while the planning agent still ran in the background; the stop hook saw no progress and paused the run for about 10 minutes until it resumed (<a href="${ISSUES}/issues/496">#496</a>).`,
        `The build PR conflicted on <code>spec.md</code>: the spec PR had been squash-merged, the ship reused the old branch (<a href="${ISSUES}/issues/494">#494</a>).`,
        `The first CI run failed on import order, which a stale local ruff cache had hidden (<a href="${ISSUES}/issues/495">#495</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs the task API; <code>POST /tasks</code> and <code>GET /tasks</code> answer, smoke 4 of 4. No question stopped the ship.' },
    ],
    links: [
      { label: 'PR: the task API', href: `${API}/pull/3` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/4` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard3-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard3-web … · /component:add taskboard3-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard3-web …', at: 154.382, time: '7 min',
    sections: [
      { heading: 'Claude does', text: 'Creates the Next.js repo from its template, adds it to <code>system.yaml</code> with its own host in dev, merges that PR on green CI and waits until dev runs it.' },
      { heading: 'What went wrong', items: [
        `The preview put the new repo under the personal account instead of the system's organisation; Claude added <code>--org ika100-demo</code> itself (<a href="${ISSUES}/issues/497">#497</a>).`,
      ] },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard3-web.taskboard3-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard3-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/5` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 172.749, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'This feature spans three repos, so it takes the system route: one system spec in the gitops repo. The API moves to Postgres, the web UI lists tasks and creates them with a form.' },
      { heading: 'Claude asks, you answer', items: [
        'List order → oldest first',
        'Due date in the web UI → <code>YYYY-MM-DD</code>',
        'The five page texts → yes, in English',
        'Database down → the API answers <code>503</code> and reports not ready, but stays healthy',
        'Tasks held in memory → lost once on the switch',
        'Backups → a separate step before prod',
        'Sign-in → none for now',
      ] },
      { heading: 'Result', text: '16 criteria, approved and merged. The product-manager first tagged two criteria as smoke tests in a repo that has none, and the spec check sent them back (<a href="https://github.com/ika100/sdlc-foundry/issues/498">#498</a>).' },
    ],
    links: [
      { label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-tasks-in-postgres-seen-and-created-in/spec.md` },
      { label: 'PR: the spec', href: `${GITOPS}/pull/7` },
    ],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 001 · /system:ship 001', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 188.314, time: '89 min',
    sections: [
      { heading: 'Claude does', items: [
        '<b>gitops</b>: Postgres and its operator in <code>system.yaml</code>, the API connected to it, the web UI pointed at the API; one PR that waits until both builds are done.',
        '<b>API</b> (22 criteria) and <b>web</b> (17 criteria), each through its own ship in parallel: a repo spec, a plan, failing acceptance tests first, code, review, PR, merge on green CI. Seven repo-spec questions were answered with the suggestions.',
        'Lands the gitops PR, installs the CloudNativePG operator, waits until dev runs both builds, smoke.',
      ] },
      { heading: 'What went wrong', items: [
        `An acceptance-test fixture held a table lock and did not end its database session, so later tests blocked. Fixing it changes an acceptance test, so the ship stopped for a person's OK (<a href="${ISSUES}/issues/499">#499</a>).`,
        `GitHub rejected the web branch's push three times with an internal error; the ship escalated instead of retrying later, and the retry 30 minutes later went through at once (<a href="${ISSUES}/issues/500">#500</a>).`,
        `Plan tasks marked parallel-safe ran one after another, because the worktree check started from the wrong commit (<a href="${ISSUES}/issues/501">#501</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres; API smoke 6 of 6, web smoke 3 of 3. One stop for a person (the test fix and the push), 1.6 minutes to answer.' },
    ],
    links: [
      { label: 'PR: the plan', href: `${GITOPS}/pull/8` },
      { label: 'PR: Postgres and wiring', href: `${GITOPS}/pull/9` },
      { label: 'PR: API on Postgres', href: `${API}/pull/4` },
      { label: 'PR: the web task list', href: `${WEB}/pull/3` },
    ],
  },
  {
    title: 'Hosts, observability and staging', short: 'Staging',
    say: 'Give staging and prod local hosts I can open in the browser, turn on the Grafana observability stack for dev and staging, and promote both components to staging. Merge the PRs once their CI is green.',
    run: '/system:set --host · observability · /instance:promote --to staging', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 384.973, time: '32 min',
    sections: [
      { heading: 'Claude does', text: 'Sets a host for staging and prod, turns on the Grafana stack (logs, metrics, traces) for dev and staging, and promotes the builds dev tested to staging. Four PRs, each merged on green CI.' },
      { heading: 'What went wrong', items: [
        `The collector stayed Degraded for about 15 minutes while its images came slowly from Docker Hub, and several merges failed on the network (one PR needed four tries). Argo still shows the observability operator OutOfSync while it is Healthy (<a href="${ISSUES}/issues/508">#508</a>).`,
      ] },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; all 8 apps of dev and staging are Synced and Healthy, Grafana answers at <code>http://grafana.localhost:8088</code>.' },
    ],
    links: [
      { label: 'PR: staging host', href: `${GITOPS}/pull/11` },
      { label: 'PR: observability', href: `${GITOPS}/pull/13` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/14` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo)', command: 'Release the API and the web UI from the builds staging tested', at: 426.299, time: '11 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos, then tags <code>v0.1.0</code> on the commit staging runs (spec 138): the tag never rebuilds, it gives the tested image its version.',
        'A follow-up PR per repo adds the changelog and moves <code>main</code> to the next development version.',
      ] },
      { heading: 'Result', text: 'Both releases point at exactly the images staging tested. Journey 2 needed 25 minutes here, with a release PR before the tag, a lock-file fix and a staging round.' },
    ],
    links: [
      { label: 'PR: API follow-up', href: `${API}/pull/5` },
      { label: 'PR: web follow-up', href: `${WEB}/pull/4` },
    ],
  },
  {
    title: 'Backups and the prod PR', short: 'Prod PR',
    say: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR for both components, but don\'t merge it.',
    run: '/resource:add backups --type bucket · /instance:promote --to prod', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 445.912, time: '11 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups: a daily backup of the prod database at 03:00 UTC, kept 30 days. Since spec 139 no component has to use the bucket.',
        `Opens the prod PRs: both components at 0.1.0, Postgres with three instances. <code>--version</code> takes one component per call, so there are two PRs (<a href="${ISSUES}/issues/505">#505</a>).`,
      ] },
      { heading: 'The prod check', text: `Before anything reaches prod the promotion shows its evidence. Here it warned that staging had no smoke record, because staging was promoted by hand (<a href="${ISSUES}/issues/503">#503</a>); Claude ran the staging smoke (5 of 5, 2 of 2) and the warning was gone. The digests matched staging and CI was green.` },
    ],
    links: [
      { label: 'PR: backups bucket', href: `${GITOPS}/pull/16` },
      { label: 'PR: API to prod', href: `${GITOPS}/pull/18` },
      { label: 'PR: web to prod', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod.', run: 'merge the prod PRs · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PRs, #18 first, then update #19 and merge it, and verify prod.', at: 465.238, time: '14 min',
    sections: [
      { heading: 'Claude does', text: 'Merges the API\'s prod PR, updates and re-renders the web PR it conflicts with and merges it, waits for Argo and runs the smoke tests against prod.' },
      { heading: 'What went wrong', items: [
        `The promotion had left two generated operator files uncommitted, so the first CI run of the API's prod PR failed (<a href="${ISSUES}/issues/504">#504</a>).`,
        `The wait for the web app ended red on a passing DNS timeout inside the cluster; Argo retried by itself and a second wait was green (<a href="${ISSUES}/issues/506">#506</a>).`,
      ] },
      { heading: 'Result', text: 'Prod runs both components at 0.1.0; smoke 5 of 5 and 2 of 2, Postgres 3 of 3 ready.' },
    ],
    links: [
      { label: 'PR: API to prod', href: `${GITOPS}/pull/18` },
      { label: 'PR: web to prod', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:restore postgres --env prod --to latest · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 495.403, time: '13 min',
    sections: [
      { heading: 'Claude does', items: [
        'Prod had no task yet, so Claude asked and created the "Prod check" task through the prod API.',
        'Restores the prod database from its backups to a separate copy next to the running one; prod keeps serving.',
        'Queries the copy read-only: the task created in prod is there, with the same id. Then discards the copy and its volumes with <code>--confirm prod</code>.',
      ] },
      { heading: 'What went wrong', items: [
        `The first scheduled backup had run before the backups bucket was ready and failed, so Claude took a new backup before the restore (<a href="${ISSUES}/issues/507">#507</a>).`,
      ] },
      { heading: 'Result', text: 'A checked restore, without touching prod. <code>--switch</code> would make the copy the active database in a real recovery.' },
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
  { from: 5, title: 'Part 2: a database and a web UI', text: 'One system spec across three repos: Postgres instead of memory, and a Next.js web UI.' },
  { from: 8, title: 'Part 3: staging, a release, prod and a restore', text: 'Hosts, observability, a release from the tested builds, prod with daily backups, and a restore drill.' },
];

/** The run at a glance (from the recording, the journey record and the demo repos). */
export const glance: { value: string; label: string }[] = [
  { value: '≈ 4 h 15', label: 'from an empty folder to a checked restore, CI rounds included' },
  { value: '5 min', label: 'of a person\'s time: 17 answers, 3 stops on a platform problem' },
  { value: '3 repos', label: 'API, web UI and gitops, from an empty folder to prod' },
  { value: '27', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
