# Real-core compatibility tests

These tests start an actual controller process and exercise the same `ClashAPI`
used by the integration. They verify:

- authentication and `/version` reads;
- automatic HTTP and WebSocket endpoint detection;
- payload shapes used by the coordinator for proxies, traffic, connections,
  memory, configs, providers, rules, and groups when supported;
- a selector read, switch to `REJECT`, read-back, and restoration to `DIRECT`;

Run every compatible binary for the current platform with:

```bash
python -m pip install -r tests/core_compatibility/requirements.txt
python tests/core_compatibility/run.py
```

Run only selected cores with:

```bash
python tests/core_compatibility/run.py clash_meta mihomo
```

Assets are pinned in `assets.json`. Darwin arm64 and Linux amd64 are currently
covered. Archives and extracted binaries are stored under
`.cache/core-compatibility`, verified by SHA-256 before execution, and ignored by
Git.

Mihomo and legacy Clash.Meta assets come from MetaCubeX releases. The original
Dreamacro Clash and Clash Premium repositories/releases are no longer available,
so their final binaries come from the explicitly identified Kuingsmile backup.
They remain compatibility fixtures, not recommended production downloads.
