// The steps of the recorded journey (2026-11-05, sdlc-foundry 5.8.3 → 5.9.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the demo repos and spec 136 ("Measured on 2026-11-05").

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard2-gitops`;
const API = `${ORG}/taskboard2-api`;
const WEB = `${ORG}/taskboard2-web`;
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
    say: 'Create a system named taskboard2 with one Python service, taskboard2-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard2.yaml --public', command: 'Create a system named taskboard2 with one Python service, taskboard2-api, …', at: 0, time: '1 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a four-line manifest, previews the run with <code>--dry-run</code>, then runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both, links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image. The organisation\'s <code>GITOPS_TOKEN</code> secret covers the service, so no token step is left for you.' },
    ],
    links: [
      { label: 'taskboard2-gitops', href: GITOPS },
      { label: 'taskboard2-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/1` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard2-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 8.359, time: '15 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and runs <code>devbox run cluster-up</code>: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard2-api --expose</code>: one PR with the route, merged on green CI.',
        'Checks that Argo reports the app Synced and Healthy.',
      ] },
      { heading: 'Result', text: '<code>http://taskboard2-api.taskboard2-dev.localhost:8088/health</code> answers 200. Most of the 15 minutes are two CI rounds and creating the cluster.' },
    ],
    links: [{ label: 'PR: expose the API', href: `${GITOPS}/pull/2` }],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard2-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/system:spec "create and list tasks …"', command: 'For taskboard2-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 45.757, time: '4 min',
    sections: [
      { heading: 'Claude does', text: 'The product-manager agent drafts the spec with acceptance criteria and asks every decision that is yours, each with a suggested answer.' },
      { heading: 'Claude asks, you answer', items: [
        'Title rules → required, trimmed, 1 to 200 characters',
        'Due date → optional, <code>YYYY-MM-DD</code>',
        'List order → oldest first',
        'Storage → in memory, one replica',
      ] },
      { heading: 'Result', text: '12 acceptance criteria. Since 5.9.0 a feature of one component is offered the shorter component route (<code>/component:spec</code> in its repo); this run still took the system route.' },
    ],
    links: [{ label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-create-and-list-tasks/spec.md` }],
  },
  {
    title: 'Approve the spec', short: 'Approve', say: 'Approve the spec', run: '/system:spec approve 001', command: '(Approve, the recommended answer)', at: 58.231, time: '2 min',
    sections: [
      { heading: 'Claude does', text: 'Marks the spec approved and merges its PR on green CI. Nothing is built from a draft.' },
    ],
    links: [{ label: 'PR: the spec', href: `${GITOPS}/pull/4` }],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/system:plan 001 · /system:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 65.54, time: '45 min',
    sections: [
      { heading: 'Claude does', items: [
        'Plans the spec across the repos (one repo here) and merges the plan.',
        'Writes the service\'s own spec from the plan (24 criteria), plans it, writes failing acceptance tests first, then code until they pass; review, PR, merge on green CI.',
        'Waits until dev runs the merged build and runs the smoke tests against it.',
      ] },
      { heading: 'What went wrong', items: [
        `The pin PR that moves dev to the new build stayed blocked: GitHub had held its <code>ci</code> run for approval and the run then never started. Fixed in the platform as <a href="${ISSUES}/pull/464">#464</a>: the pin workflow now approves every held run and retries a CI run that never started.`,
      ] },
      { heading: 'Result', text: 'Dev runs the task API; <code>POST /tasks</code> and <code>GET /tasks</code> answer, smoke green. The ship asked no question: since 5.9.0 the platform takes suggested answers in an unattended ship by itself (spec 141).' },
    ],
    links: [
      { label: 'PR: the plan', href: `${GITOPS}/pull/5` },
      { label: 'PR: the task API', href: `${API}/pull/4` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/6` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard2-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard2-web … · /component:add taskboard2-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard2-web …', at: 209.271, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'Creates the Next.js repo from its template, adds it to <code>system.yaml</code> with its own host in dev, and merges that PR on green CI.' },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard2-web.taskboard2-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard2-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/8` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 002', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 228.326, time: '5 min',
    sections: [
      { heading: 'Claude does', text: 'One system spec for three repos: the API moves to Postgres, the web UI lists tasks and creates them with a form. Four questions, answered with the suggestions, then approved.' },
      { heading: 'Result', text: '12 criteria; every story names the repos that take part.' },
    ],
    links: [{ label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/002-persist-tasks-in-postgres-and-manage/spec.md` }],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 002 · /system:ship 002', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 245.096, time: '72 min',
    sections: [
      { heading: 'Claude does', items: [
        '<b>gitops</b>: Postgres declared in <code>system.yaml</code>, the API connected to it, the web UI pointed at the API; one PR.',
        '<b>API</b> and <b>web</b>, each through its own ship in parallel: a repo spec, a plan, failing acceptance tests first, code, review, PR, merge on green CI, pin to dev, smoke.',
        'The API answers <code>503</code> while the database is down and recovers by itself.',
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres; API smoke 7 of 7, web smoke 8 of 8. A task added in the web UI survives a restart of the API. No question and no manual step stopped the ship.' },
    ],
    links: [
      { label: 'PR: the plan', href: `${GITOPS}/pull/11` },
      { label: 'PR: Postgres and wiring', href: `${GITOPS}/pull/12` },
      { label: 'PR: API on Postgres', href: `${API}/pull/6` },
      { label: 'PR: the web task list', href: `${WEB}/pull/4` },
    ],
  },
  {
    title: 'Hosts, observability and staging', short: 'Staging',
    say: 'Give staging and prod local hosts I can open in the browser, turn on the Grafana observability stack for dev and staging, and promote both components to staging. Merge the PRs once their CI is green.',
    run: '/system:set --host · observability · /instance:promote --to staging', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 415.717, time: '9 min',
    sections: [
      { heading: 'Claude does', text: 'Sets a host for staging and prod, turns on the Grafana stack (logs, metrics, traces) for dev and staging, and promotes the builds dev tested to staging. Four PRs, each merged on green CI.' },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; a task created through the staging API shows on the staging web page, and Prometheus has metrics from both environments.' },
    ],
    links: [
      { label: 'PR: observability', href: `${GITOPS}/pull/18` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/19` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo) · /instance:promote --to staging', command: 'Release the API and the web UI from the builds staging tested', at: 439.283, time: '25 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos, then a release PR with the changelog and the version 0.2.0, merged on green CI, and tags <code>v0.2.0</code>.',
        'The tag never rebuilds: it gives the image staging-to-be already has its version. The release builds go to dev, their smoke passes, and they are promoted to staging.',
      ] },
      { heading: 'What went wrong', items: [
        `The API's release PR bumped the version but not its line in <code>uv.lock</code>, so the image build failed until the lock was refreshed. Fixed in the platform as <a href="${ISSUES}/pull/468">#468</a>.`,
        'The tags were pushed before main had built the release images, so the tag jobs ran again once the images existed.',
      ] },
      { heading: 'Result', text: 'Staging runs exactly the v0.2.0 builds; the prod check sees the same image digest in staging and in the release.' },
    ],
    links: [
      { label: 'PR: API release', href: `${API}/pull/7` },
      { label: 'PR: web release', href: `${WEB}/pull/5` },
      { label: 'PR: release builds to staging', href: `${GITOPS}/pull/22` },
    ],
  },
  {
    title: 'Backups and the prod PR', short: 'Prod PR',
    say: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR for both components, but don\'t merge it.',
    run: '/resource:add backups --type bucket · /instance:promote --to prod --pr', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 498.156, time: '9 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups and lets the API use it (the platform still needs a component that uses the bucket; spec 139 would remove that).',
        'Opens the one prod PR: both components at 0.2.0, Postgres with three instances, a daily backup at 03:00 UTC kept 30 days.',
      ] },
      { heading: 'The prod check', text: 'Before anything reaches prod the promotion shows its evidence: the release image has the digest staging tested, smoke passed in dev and staging, no open smoke-failure or alert issue. Here it was clean on the first try.' },
    ],
    links: [
      { label: 'PR: backups bucket', href: `${GITOPS}/pull/23` },
      { label: 'PR: prod', href: `${GITOPS}/pull/24` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod.', run: 'merge the prod PR · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PR and verify prod.', at: 517.321, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'Merges the prod PR, waits for Argo, runs the smoke tests against prod, checks the database and the first backup, and restarts the API to show the data stays.' },
      { heading: 'Result', text: 'Prod runs both components; smoke 7 of 7 and 8 of 8, Postgres 3 of 3 ready, the first backup completed right after the deploy.' },
    ],
    links: [{ label: 'the prod PR', href: `${GITOPS}/pull/24` }],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:restore postgres --env prod --to latest · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 534.392, time: '10 min',
    sections: [
      { heading: 'Claude does', items: [
        'Restores the prod database from its backups to a separate copy next to the running one; prod keeps serving.',
        'Queries the copy read-only: the task created in prod is there, with the same id.',
        'Discards the copy and its volumes with <code>--confirm prod</code>; the backups in the bucket stay.',
      ] },
      { heading: 'Result', text: 'A checked restore, without touching prod. <code>--switch</code> would make the copy the active database in a real recovery.' },
    ],
    links: [
      { label: 'PR: restore', href: `${GITOPS}/pull/25` },
      { label: 'PR: discard', href: `${GITOPS}/pull/26` },
    ],
  },
];

/** The three recorded parts: the index of their first step and a heading. */
export const parts: { from: number; title: string; text: string }[] = [
  { from: 0, title: 'Part 1: from an empty folder to an endpoint in dev', text: 'One Python service, one spec, a local cluster.' },
  { from: 5, title: 'Part 2: a database and a web UI', text: 'One system spec across three repos: Postgres instead of memory, and a Next.js web UI.' },
  { from: 8, title: 'Part 3: staging, a release, prod and a restore', text: 'Hosts, observability, a release from the tested builds, prod with daily backups, and a restore drill.' },
];

/** The run at a glance (from the recording and the demo repos). */
export const glance: { value: string; label: string }[] = [
  { value: '≈ 3 h 50', label: 'of work for the whole journey, CI rounds included' },
  { value: '0', label: 'questions during the ships; 8 asked before the two specs' },
  { value: '3 repos', label: 'API, web UI and gitops, from an empty folder to prod' },
  { value: '34', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
