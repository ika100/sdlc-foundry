// `ideal` is the step without the run's stalls; '–' when the step is only part of this demo.
// The steps of the recorded demo run (2026-11-03, sdlc-foundry 5.6.0) for DemoWalkthrough.astro.
// `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from the recording,
// the demo repos and docs/BASELINES.md ("The 2026-11-03 demo run").

const API = 'https://github.com/ika100/demo-taskboard-api';
const GITOPS = 'https://github.com/ika100/demo-taskboard-gitops';
const SPEC = `${API}/blob/main/docs/specs/001-create-and-list-tasks`;
const ISSUES = 'https://github.com/ika100/sdlc-foundry/issues';

export interface Section { heading: string; text?: string; items?: string[]; code?: string }
export interface Step {
  title: string; short: string;
  /** what you would say in Claude Code; empty when the step needs no input */
  say: string;
  /** the command that runs (the plugin command Claude picks for `say`, or the shell command) */
  run: string;
  /** what was typed in the recording */
  command: string; at: number; measured: string; ideal: string;
  sections: Section[]; links: { label: string; href: string }[];
}

export const steps: Step[] = [
  {
    title: 'Create the system', short: 'System', say: 'Create a taskboard system with one Python service for a task API, in public repos', run: '/system:new taskboard.yaml --public', command: '/system:new taskboard.yaml --public', at: 0, measured: '3 min', ideal: '3 min',
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
    title: 'Merge and start a local cluster', short: 'Cluster', say: 'Merge the PR once its CI is green, then start a local cluster', run: 'devbox run cluster-up', command: 'Merge PR #2 once its CI is green, then run cluster-up', at: 20.542, measured: '6 min', ideal: '2 min',
    sections: [
      { heading: 'Claude does', items: [
        'Waits for the PR\'s CI and merges it.',
        'Runs <code>devbox run cluster-up</code> in the gitops repo: a k3d cluster with ArgoCD and the Gateway API, then the root Application.',
        'Waits for the API repo\'s first <code>main</code> build to publish its image, then checks that Argo reports the app Synced and Healthy.',
      ] },
      { heading: 'Result', text: '<code>/health</code>, <code>/ready</code> and <code>/docs</code> answer 200. The 4 extra minutes were the first image build; in a real flow it runs while the spec is written.' },
    ],
    links: [{ label: 'API repo CI runs', href: `${API}/actions` }],
  },
  {
    title: 'Expose the API', short: 'Expose', say: 'Make the API reachable from my browser', run: '/component:set demo-taskboard-api --expose', command: 'yes, expose it and merge the PR once CI is green', at: 33.552, measured: '2 min', ideal: '–',
    sections: [
      { heading: 'Claude does', text: 'Runs <code>/component:set demo-taskboard-api --expose</code>: one PR that adds the route and the expose flag to <code>system.yaml</code>. Merges it after CI; Argo syncs about 20 s later.' },
      { heading: 'Result', text: 'A URL on the local Gateway: <code>http://demo-taskboard-api.demo-taskboard-dev.localhost:8088</code>. Only needed for this demo; a component declared with <code>expose</code> from the start skips it.' },
    ],
    links: [{ label: 'PR: expose the API', href: `${GITOPS}/pull/3` }],
  },
  {
    title: 'Write the spec', short: 'Spec', say: 'I want to create and list tasks, each with a title and an optional due date, kept in memory', run: '/component:spec "tasks: create and list tasks …"', command: '/component:spec "tasks: create and list tasks with a title and an optional due date, kept in memory"', at: 43.8, measured: '24 min', ideal: '4 min',
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
      { heading: 'Result', text: '11 acceptance criteria (<code>AC-001.1</code> … <code>AC-001.11</code>), two of them smoke-tagged for the running service. Most of the 24 minutes the questions waited for an answer.' },
    ],
    links: [{ label: 'spec.md', href: `${SPEC}/spec.md` }],
  },
  {
    title: 'Approve the spec', short: 'Approve', say: 'Approve the spec', run: '/component:spec approve 001', command: 'Approve spec 001 now? → Approve', at: 115.0509, measured: 'in the 24 min', ideal: '–',
    sections: [
      { heading: 'Claude does', text: 'Marks the spec approved, opens the spec PR and merges it once CI is green. Approval is the one decision the build waits for.' },
    ],
    links: [{ label: 'PR: the approved spec', href: `${API}/pull/2` }],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev', run: '/component:ship 001', command: '/component:ship 001', at: 126.412, measured: '20 min', ideal: '17 min',
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
    title: 'An escalation, as it happened', short: 'Escalation', say: 'Accept the formatter\'s change to the tests, it is formatting only', run: '/component:ship 001', command: '/component:ship 001 accept the lint-fix change, it is formatting only', at: 158.82, measured: 'in the ship time', ideal: 'no longer happens',
    sections: [
      { heading: 'Why it stopped', text: 'The formatter rewrote the committed acceptance tests (<code>timezone.utc</code> → <code>UTC</code>). The build may not decide on its own that a changed test is harmless, so it stopped and asked. Accepting it resumed the run.' },
      { heading: 'Since then', text: 'Fixed: the tester formats the tests before committing them, so this stop no longer happens.' },
    ],
    links: [{ label: 'issue #367', href: `${ISSUES}/367` }],
  },
  {
    title: 'Deploy to dev', short: 'Deploy', say: '', run: '/component:ship 001 (continues)', command: '/component:ship 001 (deploy)', at: 185.972, measured: '27 min', ideal: '3 min',
    sections: [
      { heading: 'Claude does', items: [
        'The service\'s CI asks the gitops repo to pin dev to the new image; a pin PR opens and merges after its checks.',
        'Waits until Argo runs the new image, then runs the dev smoke tests for the smoke-tagged criteria.',
      ] },
      { heading: 'What went wrong', items: [
        `The pin PR waited 23 minutes for a manual approval of its checks, a GitHub rule for bot-opened PRs on public repos (<a href="${ISSUES}/368">#368</a>, fixed).`,
        `The dev smoke was skipped with "could not read the gitops-app" (<a href="${ISSUES}/369">#369</a>, fixed: retried and the error is named).`,
      ] },
      { heading: 'Result', text: 'Dev runs the new image, Argo Synced and Healthy.' },
    ],
    links: [{ label: 'PR: pin dev', href: `${GITOPS}/pull/4` }],
  },
  {
    title: 'Use it', short: 'Use it', say: 'Create a task with a due date in dev and list all tasks', run: 'curl -X POST $U/tasks … ; curl $U/tasks', command: 'curl -X POST $U/tasks … ; curl $U/tasks', at: 216.079, measured: '< 1 min', ideal: '< 1 min',
    sections: [
      { heading: 'Result', text: 'The new endpoint answers in dev: a task with a due date is created and listed next to one without.', code: '$ curl -s -X POST $U/tasks -H \'content-type: application/json\' \\\n    -d \'{"title": "Ship the demo", "due_date": "2026-11-10"}\'\n{"id":"3d6f8784-…","title":"Ship the demo","due_date":"2026-11-10",…}' },
    ],
    links: [{ label: 'the tasks endpoint', href: `${API}/blob/main/src/demo_taskboard_api/tasks_api.py` }],
  },
];

/** The run at a glance (from the recording, the demo repos and docs/BASELINES.md). */
export const glance: { value: string; label: string }[] = [
  { value: '28–30 min', label: 'from an empty folder to the endpoint in dev, without the stalls' },
  { value: '8', label: 'questions Claude asked you before writing the spec' },
  { value: '11 / 11', label: 'acceptance criteria met, each traced to a test' },
  { value: '96 %', label: 'test coverage after the build' },
  { value: '5', label: 'real pull requests in the public demo repos' },
];
