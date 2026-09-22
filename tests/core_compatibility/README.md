# Three-layer test system

The repository has one test system with three execution layers:

1. `integration` runs fast Home Assistant contracts without a core process.
2. `system` starts each pinned core and loads the integration in a real Home
   Assistant test instance. Protocol compatibility belongs to the separate
   `clash-controller-api` repository.
3. `release` runs integration tests and the complete Home Assistant/core matrix,
   including slower outage, retry, recovery, and timeout scenarios.

Install the single dependency set and run a layer with:

```bash
python -m pip install -r tests/requirements.txt
python tests/run.py integration
python tests/run.py system
python tests/run.py system --core clash_meta --full
python tests/run.py release
```

The system layer runs all pinned cores by default. Select individual cores by
repeating `--core`.

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
They remain compatibility fixtures, not recommended production downloads.
