**`cplat platform runs journey measure` counts the tokens of every repo session and follows component ships (#865).** The token
total read only the coordinator and its subagents: the headless repo sessions and their subagents went into the time split but not
into the tokens, and the repo sessions of a component ship (`cplat component ship`) were not found at all, so their minutes showed as
unattributed waiting. Now a component ship is a root like a system ship, every session and subagent is counted once (by message id),
each step's tokens include the repo sessions that worked in it, and the output splits the tokens into coordinator, its subagents,
repo sessions and their subagents. Journey 22 measures 42.6 M tokens instead of 19.5 M.
