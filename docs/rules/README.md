# The rule register

For maintainers of the platform; agents do not load this file. Spec 168
([spec](../specs/168-agent-rules-state-their-reason-and-can/spec.md),
[design](../specs/168-agent-rules-state-their-reason-and-can/design.md)) asks that every rule in an agent or command
prompt state its reason and that the few rules no tool can enforce are named. The register is where that is recorded,
and `cplat platform rules check` validates it on every run of CI.

## Where entries live

- `register.yml`: `baseline` (the commit and the total prompt bytes; the prompts may never grow past it, and it rises
  only through `cplat platform rules rebaseline`, which records each raise in `baseline.history`) and `hard:` (at most 20 distinct hard rules, each with an `enforced_by` command or CI job, or an
  `intentional_prose_rule` of at least 3 words saying why no tool can enforce it).
- `plugins/<p>/<kind>/<path>.yml`: one file per prompt `plugins/<p>/<kind>/<path>.md`, with an entry for every rule
  sentence (`id`, `text`, `class`, and the keys of that class). The `text` is a quote of the prompt sentence.

## The classes

- `hard`: departing from it does harm that cannot be undone or overrides the user's consent or a gate's integrity.
  Only the keys of `register.yml`; the prompt marks the sentence `**Hard rule:**`.
- `practice`: a way of working with a stated purpose; an agent may depart where the purpose does not apply.
- `experience`: a practice added after an incident; its `source` names the issue (`#<n>`).
- `not a rule`: the sentence has a rule word but instructs nobody. The check fails (`hidden-rule`) a sentence with a condition word that reads as an instruction:
  it addresses `you`, or, after labels and a leading `If …,`/`When …,` clause, starts with a verb such as `read`.
- `retired`: a rule removed because a `cplat` command or CI job now does it, because it repeats another rule, or
  because its cause cannot recur. The entry keeps the removed sentence, the date, the reason.

## Rewriting rules

1. Every hard, practice and experience sentence carries a reason clause (`so that`, `because`, `since`, `otherwise`)
   of at least 3 words.
2. A practice or experience never keeps `only when`, `only if`, `unless` or `except`; state the purpose instead.
3. Issue, spec and ADR references go to the entry's `source`; references alone are no reason.
4. A phrase that code depends on is marked in its test with `# interface: <reason>` and stays verbatim; no other phrase
   is pinned, so reword freely and add the reason around it.
5. An instruction with a condition (`only when`, `only if`, `unless`, `except`) is never classed `not a rule`: class it
   `practice` and state its purpose, or reword it as a statement.
6. A prompt never grows: the files of a change total at most the bytes they had before it, and the prompts in all stay
   within `baseline.prompt_bytes` (see Raise the baseline).

## Add a rule

Write the sentence in the prompt with its reason, then add an entry to the prompt's register file (next free `R<n>`,
the class and `source`). A new hard rule also needs a `hard:` key with its enforcement or its reason. Check with
`cplat platform rules check --only <prompt file>`.

## Raise the baseline

When a needed sentence takes the prompts past `baseline.prompt_bytes`, commit the change, run both benchmarks the eval
gate asks for (`cplat platform runs benchmark <workflow> --plugins plugins --reset-first` for `quick-task` and
`build`), then run `cplat platform rules rebaseline --reason "<why>"`. It refuses a dirty tree, a reason under 3 words
and a failing gate (it prints the failures with the benchmark command to run) and leaves the register unchanged. It
does nothing when the prompts are not larger than the baseline, and never lowers it. On success it writes the new
commit and total and a `history` entry (date, old and new bytes, reason, benchmark run ids); commit
`docs/rules/register.yml`. `cplat platform pr-check` (rule `rules-baseline`) shows the raise with its reason and run
ids, and fails a raise without its history entry, so a hand edit is caught.

## Test a prompt

A test checks structure, not sentences: that the prompt points to the reference, command, slash command or heading it
needs. `tests/cplat/structure.py` offers `refs`, `points_to` and `headings` for this, for example
`points_to(BUILD, "plugins/component/references/build-pr.md")`. Behaviour is left to the eval gate. A string literal
of 4 or more words that occurs verbatim in a prompt fails `cplat platform rules check` (`sentence-pin`); where code
depends on that exact literal (a `cplat` output line a prompt quotes, the `**Hard rule:**` marker), keep it and add
`# interface: <reason of 3 or more words>` on its line or the line above. A marker that covers no such literal, or whose
reason is too short, fails too. The check also fails a link, anchor, plugin-root path, `cplat <noun> <verb>` or
`/<plugin>:<command>` in a prompt that does not resolve. Decision:
[ADR-103](../adr/103-prompt-tests-check-structure-not-wording.md).

## Retire a rule

Remove the sentence from the prompt, then change its entry to `class: retired` with `retired` (the date), `reason`
and, where a tool now does the work, `enforced_by`. Run the two benchmarks for the change; `cplat platform pr-check
--fix` writes `benchmark_runs` into the entry. The retro proposes retirements under "Rules to retire": experience
rules whose issue is closed and whose cause no longer occurs.
