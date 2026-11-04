**The CI failure summary shows the log of a failed job whose run is still in progress (#399).** `gh run view --log-failed` serves
nothing until the whole run is complete, so a check that failed while its sibling jobs still ran (the three parallel e2e parts of
spec 134) was summarised without a log line and called "not a GitHub Actions run". `cplat pr wait` and ship now fetch the failed job's
own log when the run's log is empty, and a check that still has no log says why (`run still in progress`, `gh error: …`, or no log
lines); "not a GitHub Actions run" is left for checks without an Actions run link.
