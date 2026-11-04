// The steps of the recorded demo run (2026-11-03, sdlc-foundry 5.6.0) for DemoWalkthrough.astro.
// `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from the recording,
// the demo repos and docs/BASELINES.md ("The 2026-11-03 demo run").

const API = 'https://github.com/ika100/demo-taskboard-api';
const GITOPS = 'https://github.com/ika100/demo-taskboard-gitops';
const SPEC = `${API}/blob/main/docs/specs/001-create-and-list-tasks`;
const ISSUES = 'https://github.com/ika100/sdlc-foundry/issues';
const WEB = 'https://github.com/ika100/demo-taskboard-web';
const SYS_SPEC = `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-and-web-task-list`;

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
];

/** The two recorded parts: the index of their first step and a heading. */
export const parts: { from: number; title: string; text: string }[] = [
  { from: 0, title: 'Part 1: from an empty folder to an endpoint in dev', text: 'One Python service, one spec, a local cluster.' },
  { from: 9, title: 'Part 2: a database and a web UI', text: 'One system spec across three repos: Postgres instead of memory, and a Next.js web UI.' },
];

/** The run at a glance (from the recording, the demo repos and docs/BASELINES.md). */
export const glance: { value: string; label: string }[] = [
  { value: '≈ 85 min', label: 'of work for both parts, every wait cut' },
  { value: '8 + 10', label: 'questions Claude asked before writing the two specs' },
  { value: '3 repos', label: 'API, web UI and gitops, changed by one system spec' },
  { value: '1 resource', label: 'Postgres, declared once in system.yaml; tasks survive a restart' },
  { value: '13', label: 'real pull requests in the public demo repos' },
];
