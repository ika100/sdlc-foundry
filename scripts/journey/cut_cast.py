"""Cut one recorded journey into a walkthrough cast (from join_part.py, without a base).

  python3 join_part.py <base.cast> <part.cast> <part-markers.txt> <says.txt> <out.cast> <host> [CAP HOLD_TURN HOLD_QUESTION]

Like join_demo.py: everything before the part's first chapter is drawn instantly, every pause is at most CAP seconds
except a short real-time window from each input on (no gap over 1.5 s even there), and a hold after each question screen
and each finished turn. The host name is blanked. Prints the new marker times.
"""
import json
import re
import sys

part_path, markers_path, says_path, out_path, host = sys.argv[1:6]
CAP, HOLD_TURN, HOLD_QUESTION = (float(x) for x in (sys.argv[6:9] or ["0.004", "2.5", "2.0"]))
INPUT_WINDOW = 2.5
ANSI = re.compile(r'\x1b\[[0-9;?<>=]*[A-Za-z]|\x1b[\(\)][A-Z0-9]|\x1b[=>]')

part = open(part_path).read().splitlines()
part_header, events = json.loads(part[0]), [json.loads(l) for l in part[1:]]
events = [e for e in events if e[1] == 'o' and 'detached (from session' not in e[2]]
markers = [(float(t), label) for t, label in (l.split('\t') for l in open(markers_path).read().splitlines() if l)]
says = [l.strip() for l in open(says_path).read().splitlines() if l.strip()]

inputs, holds, seen = [], {}, set()
for i, (t, _, data) in enumerate(events):
    plain = ANSI.sub('', data)
    for s in says:
        if s not in seen and s[:24] in plain:
            seen.add(s)
            inputs.append(t)
    for m in re.findall(r'done (\d+:\d+ [AP]M)', plain):
        if ('done', m) not in seen:
            seen.add(('done', m))
            holds[i] = holds.get(i, 0) + HOLD_TURN
    if 'Enter to select' in plain and int(t) not in seen:
        seen.add(int(t))
        holds[i] = holds.get(i, 0) + HOLD_QUESTION

# Status-line redraws (spinner and timer, "✻ Working… (37m 6s · …)") are most of a long wait: they get no playback time,
# and only every SPIN_KEEP-th is kept so the timer still moves on.
SPIN = re.compile(r'(\d+m \d+s|\d+s) ·|esc to interrupt|[✻✶✳✢·✽✺*] [A-Z][a-z]+…')
SPIN_KEEP = 1   # keep every redraw (dropping some left stray characters); they still get no playback time
spinner = [len(ANSI.sub('', d).strip()) < 160 and bool(SPIN.search(ANSI.sub('', d))) for _, _, d in events]
keep, n_spin = [], 0
for i, sp in enumerate(spinner):
    if sp:
        n_spin += 1
        keep.append(n_spin % SPIN_KEEP == 0 or i in holds)
    else:
        keep.append(True)

start = markers[0][0] - 1.0
new_times, clock, prev = [], 0.0, None
for i, (t, _, _) in enumerate(events):
    if t < start:
        new_times.append(0.0)
        prev = t
        continue
    dt = 0.0 if prev is None or prev < start else t - prev
    real = any(ti <= t <= ti + INPUT_WINDOW for ti in inputs)
    if spinner[i] and not real:
        dt = 0.0
    clock += min(dt, 1.5) if real else min(dt, CAP)
    new_times.append(clock)
    clock += holds.get(i, 0.0)
    prev = t


def warp(t):
    for (orig, _, _), new in zip(events, new_times):
        if orig >= t:
            return new
    return new_times[-1]


blank = ' ' * len(host)
offset = 0.0
out = []
for (t, kind, data), new, k in zip(events, new_times, keep):
    if k:
        out.append([round(offset + new, 6), kind, data.replace(host, blank)])
for t, label in markers:
    out.append([round(offset + warp(t), 6), 'm', label])
out.sort(key=lambda e: (e[0], e[1] != 'm'))
with open(out_path, 'w') as f:
    f.write(json.dumps(part_header) + '\n')
    for e in out:
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
print(f'inputs found {len(inputs)}/{len(says)}; {new_times[-1]:.1f}s')
print('markers:', ', '.join(f'{offset + warp(t):.3f} {label}' for t, label in markers))
