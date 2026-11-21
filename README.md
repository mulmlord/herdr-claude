# herdr-claude

Claude Code sessions in [herdr](https://herdr.dev) instead of a terminal window each, with the
subagents of every session in herdr's sidebar under the session's entry.

```
 ● my-project
   Refactor the auth middleware
   claude · 3 agents · 1 shell
   ├ find callers of verify()
   │  2m · Grep verify\( in src/
   ├ review session handling
   │  <1m · Read session.rs
   └ run the test suite
      4m · Bash cargo test
```

Claude Code runs its subagents (Agent tool, forks, workflow agents) inside the session's own
process, so herdr only ever sees one agent per pane. A small watcher fills in the rest through
herdr's pane metadata tokens and a sidebar layout for Claude.

## Parts

| File | What it does |
|---|---|
| `claude-herdr` | Opens Claude in herdr: a new tab in the workspace of its project (a workspace with some pane already in that directory), else a new workspace; then brings the herdr window forward, or opens one. `claude-herdr [--prompt TEXT] [DIR] [-- CLAUDE_ARGS...]` |
| `claude-herdr-subagents` | Watcher: for each Claude session in a herdr pane it reports the running subagents and background shells as pane tokens `$subs`, `$sa1…5`, `$sa1do…5do` and `$sa_more`. Tokens carry a 30 s TTL, renewed every 10 s while unchanged, so they vanish if the watcher stops. `--once` does one pass and prints what it sends. Idle cost is a glance at `~/.claude/sessions`. |
| `claude-herdr-subagents.service` | systemd user unit for the watcher |
| `sidebar.toml` | The sidebar layout that renders the tokens |

## Requirements

- herdr 0.9.5 or newer, server running (Omarchy starts it at login).
- [omarchy-claude-sessions](https://github.com/mulmlord/omarchy-claude-sessions): the watcher reads
  running subagents and shells from its `sessions.sh`
  (`~/.config/omarchy/plugins/mulm.claude-sessions/sessions.sh`).
- `claude-herdr` is written for Omarchy/Hyprland (`hyprctl`, `omarchy-launch-tui`, `uwsm-app`),
  plus `jq`.

## Install

```bash
ln -s "$PWD/claude-herdr" "$PWD/claude-herdr-subagents" ~/.local/bin/
ln -s "$PWD/claude-herdr-subagents.service" ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now claude-herdr-subagents
cat sidebar.toml >> ~/.config/herdr/config.toml && herdr server reload-config
herdr integration install claude   # herdr resumes Claude sessions after a restart
```

Bind `claude-herdr` to a key, e.g. in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + ALT + C", "Claude Code (herdr)", "claude-herdr")
```

## Notes

- If `claude` on your PATH is a wrapper that runs the real claude in a PTY of its own, herdr sees
  the wrapper and doesn't detect Claude. Start the wrapper with `HERDR_AGENT=claude` in its
  environment (herdr reads it from `/proc`), e.g. have it re-exec itself with that set when
  `HERDR_PANE_ID` is present.
- herdr trims leading whitespace, no-break spaces included, from token values, so the rows are
  indented with U+2800 (braille blank). herdr puts its own `·` between tokens on a row.
- herdr reads Claude's state off the screen. With only background agents left the session shows
  idle/done while they run; `claude · 2 agents` on its row says otherwise.
- After a restart herdr resumes `claude --resume <id>` once a client attaches, with the default
  model and permission mode from your settings.
- Rows are cut at the sidebar width; drag the sidebar border wider to see more.

## License

MIT
