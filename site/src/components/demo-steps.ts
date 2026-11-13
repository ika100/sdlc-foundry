// The steps of the recorded journey (journey 13, 2026-11-13, sdlc-foundry 5.21.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the journey record (`cplat platform runs journey`) and the demo repos.

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard13-gitops`;
const API = `${ORG}/taskboard13-api`;
const WEB = `${ORG}/taskboard13-web`;
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
    say: 'Create a system named taskboard13 with one Python service, taskboard13-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard13.yaml --public', command: 'Create a system named taskboard13 with one Python service, taskboard13-api, …', at: 1.5, time: '4 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a short manifest and runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both (quality, tests, security scans must pass), links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image, and one PR that adds the service to the system.' },
    ],
    links: [
      { label: 'taskboard13-gitops', href: GITOPS },
      { label: 'taskboard13-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/2` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard13-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 12.277, time: '2 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and runs <code>devbox run cluster-up</code>: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard13-api --expose</code>: one PR with the route, merged on green CI, then waits until dev is Synced and Healthy.',
      ] },
      { heading: 'What went wrong', items: [
        'Claude ended its turn while the cluster start still ran in the background, so the next sentence came before it had checked the URL. It finished the check at the start of the next step; nothing was lost.',
      ] },
      { heading: 'Result', text: '<code>http://taskboard13-api.taskboard13-dev.localhost:8088/docs</code> and <code>/health</code> answer 200.' },
    ],
    links: [
      { label: 'PR: pin dev', href: `${GITOPS}/pull/3` },
      { label: 'PR: expose the API', href: `${GITOPS}/pull/4` },
    ],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard13-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/component:spec "create and list tasks …" · /component:spec approve 001', command: 'For taskboard13-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 22.381, time: '5 min',
    sections: [
      { heading: 'Claude does', text: 'A feature of one component takes the component route. The product-manager agent decides every default itself and lists it under <b>Assumptions</b>; it asks only what it may not decide. You approve the spec together with its assumptions.' },
      { heading: 'Claude asks, you answer', items: [
        'Approve spec 001 with these 10 assumptions (among them: no login, tasks are lost on a restart) → approve',
      ] },
      { heading: 'Result', text: '7 acceptance criteria and 10 assumptions, approved and merged in the repo that builds them.' },
    ],
    links: [
      { label: 'the spec', href: `${API}/blob/main/docs/specs/001-create-and-list-tasks-in-memory/spec.md` },
      { label: 'PR: the spec', href: `${API}/pull/3` },
    ],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/component:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 36.641, time: '20 min',
    sections: [
      { heading: 'Claude does', items: [
        'The architect plans the tasks; the tester writes failing acceptance tests for every criterion first, then the coders work until they pass.',
        'Review against the spec and a mutation check, then one PR, merged on green CI; waits until dev runs the merged build and runs the smoke tests against it.',
      ] },
      { heading: 'What went wrong', items: [
        `The build check looks for the acceptance-test commit by the spec id, and the tester's commit subject named the criteria instead. Claude reworded the subject and went on (a platform defect, <a href="${ISSUES}/issues/724">#724</a>).`,
        `Recording the review's findings refused a task the plan had merged into another, so this build's agent metrics are incomplete (a platform defect, <a href="${ISSUES}/issues/725">#725</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs the task API; <code>POST /tasks</code> and <code>GET /tasks</code> answer, 6 of 6 smoke tests green, 96 % coverage. No question and no stop.' },
    ],
    links: [
      { label: 'PR: the task API', href: `${API}/pull/4` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/5` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard13-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard13-web --system ika100-demo/taskboard13-gitops … · /component:add taskboard13-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard13-web …', at: 72.597, time: '5 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 2 (<code>/clear</code>): every command keeps its state in the repos. Claude creates the Next.js repo from its template, adds it to <code>system.yaml</code> with its own host in dev, merges that PR on green CI and waits until dev runs it.' },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard13-web.taskboard13-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard13-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/6` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/7` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 001 · /system:plan 001 · /system:ship 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 87.63, time: '5 min',
    sections: [
      { heading: 'Claude does', text: 'This feature spans three repos, so it takes the system route: one system spec in the gitops repo, which says what each repo must do; no code yet.' },
      { heading: 'Claude asks, you answer', items: [
        'The web UI will be open without a login, so anyone who can reach it can read and add tasks. Acceptable? → yes, open for now (a login becomes a later spec)',
        'Approve system spec 001 with these 9 assumptions → approve',
      ] },
      { heading: 'Result', text: 'A system spec with 8 acceptance criteria and 9 assumptions, approved and merged in the gitops repo.' },
    ],
    links: [
      { label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-in-postgres-with-a-web/spec.md` },
      { label: 'PR: the spec', href: `${GITOPS}/pull/8` },
    ],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 001 · /system:ship 001', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 102.32, time: '39 min',
    sections: [
      { heading: 'Claude does', items: [
        'The planner splits the spec across the three repos, every criterion assigned; the plan is merged on green CI.',
        '<b>API</b> and <b>web</b> build in parallel, each in its own session, from a repo spec written and approved from the plan; <b>gitops</b> declares Postgres and wires the API address into the web UI, in one PR kept open until both builds are in, so dev changes once. The landing step installs the database operator in the local cluster itself.',
      ] },
      { heading: 'What went wrong', items: [
        `One API test run hung after 9 tests until the platform's 9-minute limit stopped it; the service template has no per-test time limit yet (a platform defect, <a href="${ISSUES}/issues/728">#728</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres; smoke green (API 7 of 7, web 3 of 3). No question and no stop: every repo built on its first try.' },
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
    run: '/system:set --host · /system:set --observability · /instance:promote --to staging --smoke', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 175.26, time: '9 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 3. Claude sets the staging and prod hosts and turns on the Grafana stack (logs, metrics, traces) for dev and staging, each with <code>/system:set</code>, then promotes the builds dev tested to staging in one PR, which runs the staging smoke itself. Four PRs, each merged on green CI.' },
      { heading: 'What went wrong', items: [
        `The observability command does not print where Grafana answers, so Claude reported that it had no URL. Grafana was at <code>http://grafana.localhost:8088</code> (a platform defect, <a href="${ISSUES}/issues/726">#726</a>).`,
      ] },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; smoke green (API 5 passed, 2 writing tests only run in dev; web 2 of 2).' },
    ],
    links: [
      { label: 'PR: staging host and observability', href: `${GITOPS}/pull/12` },
      { label: 'PR: dev observability', href: `${GITOPS}/pull/13` },
      { label: 'PR: prod host', href: `${GITOPS}/pull/14` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/15` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo)', command: 'Release the API and the web UI from the builds staging tested', at: 197.12, time: '5 min',
    sections: [
      { heading: 'Claude does', items: [
        'Tags <code>v0.1.0</code> on the commit staging runs in both repos: CI gives the tested image its version without rebuilding it, so the 0.1.0 images have the staging images\' digests.',
        'The quality, test and security gates are not run again: CI already passed them on exactly these commits.',
        'A follow-up PR per repo adds the changelog and moves <code>main</code> to the next development version.',
      ] },
      { heading: 'What went wrong', items: [
        `In the web repo the version command refused to run while the new changelog was not yet committed; the agent moved the file aside for that one command (a platform defect, <a href="${ISSUES}/issues/727">#727</a>).`,
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
    run: '/resource:add backups --type bucket · /resource:backup postgres --env prod --to backups --schedule "0 3 * * *" · /instance:promote --all --to prod', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 210.365, time: '5 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups and a daily backup of the prod database (03:00 UTC, kept 30 days), each with its own command and PR, and merges both first, so the backup is in place before prod.',
        'Opens one prod PR for both components at 0.1.0.',
      ] },
      { heading: 'The prod check', text: 'The promotion shows its evidence before anything reaches prod: the image digests match what staging tested, dev and staging smoke passed for both components, and no smoke-failure or alert issue is open.' },
    ],
    links: [
      { label: 'PR: backups bucket', href: `${GITOPS}/pull/16` },
      { label: 'PR: daily prod backup', href: `${GITOPS}/pull/17` },
      { label: 'PR: both to prod', href: `${GITOPS}/pull/20` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', run: 'merge the prod PR · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', at: 223.847, time: '8 min',
    sections: [
      { heading: 'Claude does', text: 'The prod PR was behind <code>main</code>, so it is updated and its checks run again before the merge. Claude waits for Argo CD, runs the smoke tests against prod and creates the "Prod check" task through the prod API.' },
      { heading: 'Result', text: 'Prod runs both components at 0.1.0; all four prod apps Synced and Healthy, smoke green (API 5 passed, its writing tests run only in dev; web 2 of 2), and the "Prod check" task is the only task in prod.' },
    ],
    links: [
      { label: 'PR: both to prod', href: `${GITOPS}/pull/20` },
    ],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:restore postgres --env prod --to latest · /resource:query postgres --env prod --copy g1 · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 242.921, time: '6 min',
    sections: [
      { heading: 'Claude does', items: [
        'Restores the prod database to the latest point as a separate copy next to the running one, through a gitops PR; prod keeps serving.',
        'Queries the copy read-only with <code>/resource:query</code>: the "Prod check" task is there, with the id the prod API gave it.',
        'Discards the copy and its volumes with <code>--confirm prod</code>, through a second PR.',
      ] },
      { heading: 'Result', text: 'A checked restore without touching prod. <code>--switch</code> would make the copy the active database in a real recovery.' },
    ],
    links: [
      { label: 'PR: restore', href: `${GITOPS}/pull/21` },
      { label: 'PR: discard', href: `${GITOPS}/pull/22` },
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
  { value: '≈ 1 h 53', label: 'from an empty folder to a checked restore, CI rounds included, without a single stop' },
  { value: '35 M', label: 'tokens' },
  { value: '3', label: 'questions in the whole run, all answered with the suggested option' },
  { value: '27', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
