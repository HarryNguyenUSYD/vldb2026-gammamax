# betaMax test suite

This is the betaMax-only form of `example-test-suite`. It generates 150
deterministic cases across date, time, URL, ISBN, IPv4, and IPv6 formats.

```text
make
make smoke
make test
```

`make` compiles betaMax and all six native validators. `make smoke` runs the
first 10 generated cases and writes `results/betamax-smoke.csv`. `make test`
runs all 150 cases and writes `results/betamax.csv`. Both test targets use the
largest worker count available from CPU affinity or the system CPU count.

Each case runs in an isolated temporary directory. The runner writes the
required `input.json` and `config.json`, then launches betaMax without command
line arguments.

Resource/search boundaries in `suite-config.json` accept `-1` to disable the
boundary. The suite disables all betaMax boundaries and retains only the
300-second per-case timeout enforced by the runner.

During a run, progress is shown as `completed A/B (total C/D)`: `A/B` is the
current algorithm's completion counter and `C/D` is the counter for the entire
run. The elapsed-seconds prefix refreshes once per second.
