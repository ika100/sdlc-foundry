**`cplat quiet test-fast` sizes its pytest workers by the machine load and names an overloaded machine (#1119).** Every dispatcher unit ran `pytest -n auto`, so several units started several times the CPU count in workers, and the fixed 9-minute cap turned a slow, healthy run red. `test-fast` now uses the CPUs the load leaves free (at least 2), and a run that gives up while the load is at or above one per CPU reports `environment: machine overloaded (load X)`.

Caused by: unknown
