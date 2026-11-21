# herdr-claude

Claude Code sessions in [herdr](https://herdr.dev) instead of a terminal window each: one space
per project, every subagent in a tab of its own with the background shells it starts beside its
work, and the subagents of each session in herdr's sidebar under the session's entry.

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
process, so herdr only ever sees one agent per pane. Hooks and a small watcher fill in the rest:
a viewer follows each subagent's transcript and each background shell's output file in panes of
their own, and herdr's pane metadata tokens put the subagents in the sidebar.

```
 tab 1  claude (main session)            │ main: watch the bench
                                         │ (output of a shell the session started)
 tab 2  find callers of verify()         │ find callers…: cargo test
        ● Grep verify\( in src/          │ (output of a shell that agent started)
          │ src/auth.rs:42: verify(…)    │
```

## Parts

Every project gets a herdr space of its own, named after it. A directory below the projects root
(`$CLAUDE_HERDR_PROJECTS`, default `~/Projects`) belongs to the project at the first level under
it; any other directory is a project of its own.

| File | What it does |
|---|---|
| `herdr-project-space` | Prints the space of a directory's project, creating it when missing; `--focus` switches herdr to it. `herdr-project-space [--focus] [DIR]` |
| `herdr-here` | herdr in a new terminal, on the space of the focused terminal's project (for Omarchy's SUPER+CTRL+RETURN) |
| `claude-herdr` | Opens Claude in its project's space: in the space's only pane when that idles at a shell prompt in the directory (a fresh space), else in a new tab; then brings the herdr window forward, or opens one. `claude-herdr [--prompt TEXT] [--no-focus] [DIR] [-- CLAUDE_ARGS...]`; `$HOME` becomes the projects root. |
| `claude-herdr-move` | Moves Claude sessions from terminal windows into herdr: closes the window and resumes the conversation (`claude --resume`, same model and permission mode) in its project's space. Only sessions with nothing in flight (no turn, question, background shell or subagent) move; `--wait` waits for the others and moves each once it has been idle for 2 minutes. `claude-herdr-move` alone lists them. |
| `claude-herdr-tabs` | Claude Code hook (SubagentStart, SubagentStop, PostToolUse on Bash) for sessions in herdr: a starting subagent gets a new tab in the session's space, named after its task; a background shell gets a pane beside the work of the agent that started it (beside the main Claude pane for the session itself), further shells stacking below. Nothing takes the focus. Returns at once outside herdr (~10 ms per Bash call). |
| `claude-herdr-view` | Runs in those panes: follows a subagent's transcript (prompt, text, tool calls with the start of each result, its final report) or a shell's output file. When the work ends it closes its pane after `$CLAUDE_HERDR_LINGER` s (default 120; `q` closes now, `k` keeps it), and a tab goes with its last pane. |
| `claude-herdr-subagents` | Watcher: for each Claude session in a herdr pane it reports the running subagents and background shells as pane tokens `$subs`, `$sa1…5`, `$sa1do…5do` and `$sa_more`. Tokens carry a 30 s TTL, renewed every 10 s while unchanged, so they vanish if the watcher stops. It also names tabs instead of leaving them numbered: after the Claude session's title where Claude runs, else after the tab's directory (like tmux's automatic-rename); a tab you rename yourself keeps its name. `--once` does one pass and prints what it sends. It reads the session data the bar widget already computes (`live.json`) while that is fresh, so it costs about 1 ms of CPU per second. |
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
for f in claude-herdr claude-herdr-subagents claude-herdr-move claude-herdr-tabs claude-herdr-view \
         herdr-project-space herdr-here; do
  ln -s "$PWD/$f" ~/.local/bin/
done
ln -s "$PWD/claude-herdr-subagents.service" ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now claude-herdr-subagents
cat sidebar.toml >> ~/.config/herdr/config.toml && herdr server reload-config
herdr integration install claude   # herdr resumes Claude sessions after a restart
```

Hooks for the agent tabs, in `~/.claude/settings.json` (new sessions pick them up):

```json
"SubagentStart": [{ "hooks": [{ "type": "command", "command": "~/.local/bin/claude-herdr-tabs agent-start", "timeout": 10 }] }],
"SubagentStop":  [{ "hooks": [{ "type": "command", "command": "~/.local/bin/claude-herdr-tabs agent-stop", "timeout": 10 }] }],
"PostToolUse":   [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "~/.local/bin/claude-herdr-tabs shell", "timeout": 10 }] }]
```

Keys, e.g. in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + ALT + H", "Claude Code (herdr)", "claude-herdr")
o.rebind("SUPER + CTRL + RETURN", "Herdr (project space)", "herdr-here")
```

And so that a plain `herdr` typed in a project opens on its space, in `~/.bashrc`:

```bash
herdr() {
  if (($# == 0)) && [[ -z ${HERDR_ENV:-} ]] && command -v herdr-project-space > /dev/null; then
    herdr-project-space --focus "$PWD" > /dev/null
  fi
  command herdr "$@"
}
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
- A shell view shows what the command writes to its output file. Wrappers that hold output back
  until the command ends (output condensers such as rtk) make it appear only at the end.

## License

MIT
