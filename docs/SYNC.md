# How a line is classified

Every line profiler considers gets exactly one classification. The first rule that matches wins,
and the rule groups are consulted in the order below.

| Class | Meaning | Travels to bash | Travels to zsh |
| --- | --- | --- | --- |
| `never` | Means something different in each shell, or would make the profiles source one another. | no | no |
| `bash` | Only bash understands it. | yes | no |
| `zsh` | Only zsh understands it. | no | yes |
| `shared` | Anything else, including blank lines and comments. | yes | yes |

## Never

- Any reference to `.bashrc`, `.zshrc`, `.bash_profile`, `.zprofile`, `.zshenv`, `.zlogin`,
  `.zlogout` or `.bash_logout`, so the two files can never end up sourcing each other.
- Prompt state: `PS0`–`PS4`, `PROMPT`, `RPROMPT`, `RPS1`, `RPS2`, `PROMPT_COMMAND`, and `precmd` or
  `preexec` definitions. The escape sequences differ between the shells.
- `SHELL` and `ZDOTDIR`.

## Bash only

`shopt`, `complete`, `compopt`, `bind`, `HISTCONTROL`, `HISTFILESIZE`, `HISTTIMEFORMAT`,
`FIGNORE`, `GLOBIGNORE`, any `BASH*` assignment, any use of `BASH_SOURCE`, `BASH_VERSION`,
`BASH_VERSINFO` or `BASH_REMATCH`, and anything mentioning bash-completion.

## Zsh only

`setopt`, `unsetopt`, `bindkey`, `zstyle`, `autoload`, `zmodload`, `compinit`, `compdef`,
`compaudit`, `zle`, `emulate`, `add-zsh-hook`, the `zinit` / `zplug` / `antigen` / `antidote`
plugin managers, `plugins=(...)`, `ZSH*` and `SAVEHIST` assignments, array-style `path=(...)` and
`fpath=(...)`, `typeset -U`, global and suffix aliases, and anything mentioning oh-my-zsh,
powerlevel10k, zsh-syntax-highlighting or zsh-autosuggestions.

## Adding your own patterns

Point `PROFILER_RULES_FILE` at a JSON file. Its patterns are consulted before the built-in ones, so
they can reclassify anything.

```json
{
  "never": ["^export WORK_VPN_"],
  "bash": ["^mybash-"],
  "zsh": ["^myzsh-"]
}
```

Each value is a Python regular expression, searched against the stripped line.

# How a pass works

1. Read both profiles and split each into the lines you wrote and the managed block.
2. Compare both halves against the snapshot recorded by the previous pass. Additions are grouped
   into blank-line separated paragraphs; removals are collected line by line.
3. Apply the other side's removals. A line struck from the author's own region is withdrawn from
   the copy in the managed block. A line struck from inside a managed block is struck at its
   source too, since a managed block holds nothing but copies.
4. Append the other side's new content. Each paragraph is cut into units first: one unit per
   standalone statement, one unit per whole construct, so a function crosses over in one piece
   while the statements around it are judged on their own. A unit is appended only if every line
   in it may travel to that shell and the receiving profile does not already contain it.
5. Check the rewritten text with `bash -n` or `zsh -n`. A result that would not parse is discarded
   and reported; the file on disk is not touched and the snapshot does not advance, so the next
   pass tries again.
6. Back the file up, replace it atomically, preserving its mode and owner, then record the new
   snapshot. Because the snapshot matches what was just written, nothing bounces back.

A pass over an unrecorded home directory only takes the snapshot. Run `profiler adopt` to treat
everything currently outside the managed blocks as newly written, which merges the two files once.

## Opting a file out

Deleting the whole managed block, markers included, is read as opting that file out rather than as
deleting every mirrored line. Nothing is removed from the other profile, and the next pass starts
again from what is left. Deleting individual lines from inside an intact block is read as a
deletion and does reach the other file.
