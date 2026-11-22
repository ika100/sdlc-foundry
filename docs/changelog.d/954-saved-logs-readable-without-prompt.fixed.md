**A session reads the log `cplat quiet` saved without a permission prompt (#954).** The full log of a failed `devbox run`
step lies in `~/.cache/sdlc-foundry/logs/`, outside the repo, and only headless units had a rule to read it: an
interactive session, above all one in a worktree, stopped with a yes/no prompt each time it opened the log. The committed
`.claude/settings.json` of the platform repo and of every template now allow `Read(~/.cache/sdlc-foundry/logs/**)`; the rule
grants reading only. **Action:** run `/platform:update` in existing repos to get the rule.
