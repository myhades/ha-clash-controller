# Three-layer test system

The repository has one test system with three execution layers:

1. `unit` runs fast API, coordinator, and service tests without a core process.
2. `system` starts a pinned core and loads the integration in a real Home
   Assistant test instance. The earlier API/core compatibility checks are part
   of this layer as well.
3. `release` runs unit tests and the complete Home Assistant/core matrix,
   including slower outage, retry, recovery, and timeout scenarios.

Install the single dependency set and run a layer with:

```bash
python -m pip install -r tests/requirements.txt
python tests/run.py unit
python tests/run.py system
python tests/run.py system --core clash_meta --full
python tests/run.py release
```

The system layer defaults to Mihomo. Select multiple cores by repeating
`--core`, or use `--all-cores`.

```bash
python tests/run.py system --core clash_meta --core mihomo
python tests/run.py system --all-cores
```

Pass a local Clash configuration as the base fixture with `--config`. Dynamic
controller/proxy ports, the test secret, and the deterministic
`HA Compatibility Test` selector are injected into a temporary copy; the source
file is never modified.

```bash
python tests/run.py system --core mihomo --full --config /path/to/config.yaml
```

Assets are pinned in `assets.json`. Darwin arm64 and Linux amd64 are currently
covered. Archives and extracted binaries are stored under
`.cache/core-compatibility`, verified by SHA-256 before execution, and ignored by
Git.

Mihomo and legacy Clash.Meta assets come from MetaCubeX releases. The original
Dreamacro Clash and Clash Premium repositories/releases are no longer available,
so their final binaries come from the explicitly identified Kuingsmile backup.
They remain compatibility fixtures, not recommended production downloads. The
legacy `tests/core_compatibility/run.py` path is only a compatibility wrapper;
new automation must use `tests/run.py`.
