`cplat dispatch start --detach`, the loop restart and every unit start no longer run on uv's temporary Python, which uv deletes when the launching `uv run` exits: they go through `uv-script.sh` then, and a detach refuses such a path (#1122).


Caused by: #1096
