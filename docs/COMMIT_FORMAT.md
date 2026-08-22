# Commit update protocol

Profiler deploys through Auto Update Changer. Substantial commits declare their deployment effects in the commit body. The block is parsed as data; its values are never evaluated as shell code.

```text
!!!BEGIN UPDATE AUTO CHANGER!!!
SUMMARY: Hold back oh-my-zsh plugin lines
AUTO: application
AUTO: python-environment
AUTO: systemd
ADDENV: PROFILER_HOMES = $input
ADDENV: PROFILER_VALIDATE = true
REPROCESS: profiles --mode=adopt
USER: Check 'profiler status' once the service is back up.
!!!END UPDATE AUTO CHANGER!!!
```

## Directives

- `SUMMARY: text` prints a human-readable description in the update plan.
- `AUTO: name` selects an implementation from `deploy/modules.sh`. The name must appear in `automatic_modules` in `deploy/update_policy.json`. `application` is always selected.
- `ADDENV: KEY = value` asks the operator to accept or replace a literal default.
- `ADDENV: KEY = $input` requires an interactive value. Existing values are preserved when Enter is pressed. Keys and values are validated by policy; secret-looking keys are entered without echo.
- `REPROCESS: module flags...` runs a retry-safe application hook. Profiler's only module is `profiles`, which runs one synchronization mode against the deployed configuration. The module and exactly one flag from every required flag group must be allowed by policy.
- `USER: text` prints a manual action only after a successful deployment.

Unknown directives, modules, environment keys, values containing whitespace, missing flag groups, extra flags, and incomplete markers stop the update before deployment.

## Policy syntax

`deploy/update_policy.json` is the complete whitelist:

```json
{
  "automatic_modules": ["application", "python-environment", "systemd"],
  "environment_key_pattern": "^PROFILER_[A-Z0-9_]+$",
  "reprocess_modules": {
    "profiles": {
      "flag_groups": [
        ["--mode=sync", "--mode=adopt", "--mode=reseed"]
      ]
    }
  }
}
```

Adding a whitelist entry does not implement it. Add the matching fixed `case` branch to `deploy/modules.sh`. Reprocess implementations should be deterministic and safe to replay.

## Commands

```bash
sudo bash deploy/update.sh --plan-only
sudo bash deploy/update.sh
sudo bash deploy/update.sh --target COMMIT_OR_TAG
sudo bash deploy/update.sh --replay-commit COMMIT_OR_TAG
```

Normal updates fetch the configured upstream, require a clean checkout and fast-forward history, then deploy every commit between the recorded deployment revision and the target. `--target` stops at a selected forward revision. `--replay-commit` keeps the installed source revision and repeats only that commit's declared environment/reprocess operations.

