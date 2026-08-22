# Profiler

Profiler keeps the shared parts of `~/.bashrc` and `~/.zshrc` identical. Write a line in either
file and it appears in the other one; delete it in either file and it disappears from both.

Lines that only make sense to one shell stay where their author put them. `setopt`, `bindkey`,
`zstyle` and oh-my-zsh never reach bash; `shopt`, `complete`, `bind` and `HISTCONTROL` never reach
zsh; prompts and anything that sources a profile stay put in both directions. Every rewrite is
checked with `bash -n` or `zsh -n` before it replaces the real file, and the previous version is
kept as a backup.

It runs as a systemd service, installs and updates through
[Auto Update Changer](https://github.com/BogdanStamenovic/auto-update-changer), and is installable
as an [Ownbox](https://github.com/BogdanStamenovic/ownbox) tool.

## How the two files stay in step

Profiler owns one region of each file and never edits anything else:

```bash
# ~/.zshrc
setopt AUTO_CD                 # yours, untouched

# >>> profiler managed block >>>
# Mirrored by profiler from the other shell profile. Edit or delete these
# lines in either file; both sides are kept in step. Nothing else is touched.
export EDITOR=nvim             # arrived from ~/.bashrc
alias gs='git status'          # arrived from ~/.bashrc
# <<< profiler managed block <<<
```

Each pass compares both files against the snapshot from the last pass. Whatever you added lands in
the other file's managed block, whatever you removed is removed from both files, and the snapshot
is rewritten so nothing bounces back. A function crosses over in one piece rather than line by
line, and the statements around it are judged on their own.

Deleting the whole managed block, markers included, opts that file out instead of deleting the
originals from the other one.

The first pass on a new machine only records a snapshot. Run `profiler adopt` once when you want
the content the two files already hold to be merged.

## Install as an Ownbox tool

```bash
ownbox sync
ownbox install profiler
profiler adopt
profiler watch
```

For a login-scoped daemon instead of the system service, install the optional user unit:

```bash
install -Dm644 deploy/profiler-user.service ~/.config/systemd/user/profiler.service
systemctl --user daemon-reload
systemctl --user enable --now profiler.service
```

Ownbox reserves `update`, `rollback`, `uninstall`, `remove`, `info` and `where` for its own
launcher, so Profiler uses none of those names. Everything below passes straight through.

## Install as a system service

```bash
git clone https://github.com/BogdanStamenovic/profiler.git
cd profiler
sudo bash deploy/install.sh
sudoedit /etc/profiler.env      # set PROFILER_HOMES=/home/youruser
sudo systemctl start profiler.service
```

The service runs as root so it can maintain profiles for several accounts at once, and it watches
with inotify, falling back to polling where inotify is unavailable. `systemctl reload
profiler.service` forces a pass without a restart.

Remote updates go through Auto Update Changer:

```bash
sudo bash deploy/update.sh --plan-only
sudo bash deploy/update.sh
```

See [the commit syntax](docs/COMMIT_FORMAT.md) for the directives the updater accepts.

## Use

```bash
profiler sync         # propagate everything written since the last pass
profiler adopt        # one-time merge of the content both profiles already hold
profiler reseed       # record the current profiles without changing them
profiler watch        # stay resident and synchronize on every change
profiler status       # show what profiler currently manages
profiler doctor       # check the environment and report the resolved settings
profiler restore      # put a backed-up profile back in place
profiler cleanup      # remove every managed block and forget the stored state
```

`--dry-run` reports what a pass would do without touching a file. `--home` overrides the configured
directories, and `--env-file` reads settings from a file instead of the environment.

## Settings

Every setting is a `PROFILER_*` environment variable, read from `/etc/profiler.env` under systemd.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROFILER_HOMES` | the current user's home | Colon-separated home directories to keep in sync. |
| `PROFILER_STATE_DIR` | `/var/lib/profiler` as root, else `~/.local/state/profiler` | Snapshots and backups. |
| `PROFILER_POLL_INTERVAL` | `5` | Seconds between fallback passes when no event arrives. |
| `PROFILER_DEBOUNCE` | `0.75` | Seconds of quiet after a change before a pass runs. |
| `PROFILER_BACKUP_KEEP` | `20` | Backups kept per profile. `0` keeps every one. |
| `PROFILER_VALIDATE` | `true` | Check the result with `bash -n` / `zsh -n` before writing. |
| `PROFILER_CREATE_MISSING` | `true` | Create the other profile when it does not exist yet. |
| `PROFILER_RULES_FILE` | unset | JSON file of extra `never` / `bash` / `zsh` patterns. |
| `PROFILER_LOG_LEVEL` | `INFO` | Logging level for the service. |
| `PROFILER_BASHRC_NAME`, `PROFILER_ZSHRC_NAME` | `.bashrc`, `.zshrc` | Profile file names. |

Extra classification patterns are plain regular expressions:

```json
{
  "never": ["^export WORK_VPN_"],
  "zsh": ["^myzsh-"],
  "bash": ["^mybash-"]
}
```

[The classifier](docs/SYNC.md) documents what the built-in rules cover and how a line is decided.

## Recovering

Every write leaves a timestamped copy under the state directory.

```bash
profiler restore --list
profiler restore --shell zsh
profiler reseed
```

`profiler cleanup` removes both managed blocks and forgets the stored snapshots, leaving each file
with exactly the lines its owner wrote.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
bash -n deploy/install.sh deploy/update.sh deploy/modules.sh
```

Licensed under MIT.
