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

When both files already define the same name differently — say `alias ls` is `ls --color=auto` in
one and `eza --icons` in the other — profiler will not pick a winner for you. In a terminal it
asks:

```text
Both profiles in /home/you define alias ls, differently:
  1) .bashrc: alias ls='ls --color=auto'
  2) .zshrc: alias ls='eza --icons'
  k) keep each file's own version, and stop asking about this name
  s) skip for now, and ask again next pass
Use which in both? [1-2/k/s]
```

The answer is remembered, so it is asked once and not on every pass. The service never asks: with
nobody at a terminal it leaves both definitions alone and reports them, and you settle them the
next time you run `profiler sync` yourself. `--on-conflict apart` answers `k` for everything, and
`--on-conflict skip` only ever reports.

The first pass on a new machine only records a snapshot. Run `profiler adopt` once when you want
the content the two files already hold to be merged.

## Install

Profiler is an Auto Update Changer deployment: the service runs as root out of `/opt/profiler`,
configured by `/etc/profiler.env`, with its state under `/var/lib/profiler`. There is one
installation, reachable two ways.

Through Ownbox:

```bash
ownbox sync
ownbox install profiler
```

Ownbox clones the repository and runs the same `deploy/` scripts the manual path uses, so it
produces the same deployment rather than a second private one. `deploy/install.sh` builds
`/opt/profiler`, then `deploy/configure.sh` seeds `/etc/profiler.env` with your home directory and
starts the service. Both need root, so expect a sudo prompt.

Or directly:

```bash
git clone https://github.com/BogdanStamenovic/profiler.git
cd profiler
sudo bash deploy/install.sh
sudo bash deploy/configure.sh
```

Install from a clean checkout. `deploy/install.sh` copies the working tree into `/opt/profiler`
before building its own virtual environment, so a `.venv/` left over from development would be
copied along with it. Ownbox always clones fresh.

Either way, finish by merging what the two profiles already hold:

```bash
sudo profiler adopt
```

The service runs as root so it can maintain profiles for several accounts at once — add them to
`PROFILER_HOMES` — and it watches with inotify, falling back to polling where inotify is
unavailable. `systemctl reload profiler.service` forces a pass without a restart.

### Updating and removing

```bash
ownbox update profiler          # runs deploy/update.sh
ownbox uninstall profiler       # runs deploy/uninstall.sh
```

Or `sudo bash deploy/update.sh`, with `--plan-only` first to see the plan. The updater performs its
own fetch and fast-forward, requires a clean checkout, backs up state and the environment file, and
restarts the service. See [the commit syntax](docs/COMMIT_FORMAT.md) for the directives it accepts.

`deploy/uninstall.sh` takes the managed blocks back out of every profile it maintains, then removes
the unit and `/opt/profiler`. State, backups and `/etc/profiler.env` survive unless you pass
`--purge`; `--keep-blocks` leaves the mirrored content in place.

Do not use `ownbox rollback` here. It resets the checkout and then re-runs the update commands,
which would deploy forward again. Auto Update Changer keeps its own history, so go back with:

```bash
sudo bash deploy/update.sh --target REVISION
```

### Running it for one account only

To skip the system service, install into a virtual environment of your own and use the optional
user unit in [deploy/profiler-user.service](deploy/profiler-user.service). That instance keeps its
state in `~/.local/state/profiler` and needs no root at all.

### A note on command names

Ownbox reserves `update`, `rollback`, `uninstall`, `remove`, `info` and `where` for its own
launcher, so Profiler's CLI uses none of those names. Everything else passes straight through.
Because the deployment is root-owned, the launcher Ownbox puts on your PATH runs the deployed
binary under `sudo` with `--env-file /etc/profiler.env`, so `profiler status` reports on the
running service rather than on a private copy of the state.

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

`--dry-run` reports what a pass would do without touching a file, including anything it would
refuse to write. `--home` overrides the configured directories, `--env-file` reads settings from a
file instead of the environment, and `--on-conflict` chooses how contested definitions are handled.

Start with `--dry-run` on a real home before the first `adopt`. A long-standing configuration can
have more in it than you expect, and the dry run is the cheap way to find out.

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
