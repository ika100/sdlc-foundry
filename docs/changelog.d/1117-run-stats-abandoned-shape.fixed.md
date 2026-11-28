**Run statistics no longer count a unit's continued build as abandoned or show every repo's shape as unknown (#1117).** A unit session's `runs begin build` without `--spec` now continues the open build run instead of finishing it as abandoned and starting a second one, and the retro reads a run's own recorded `shape` when its agent entries carry none.
Caused by: unknown
