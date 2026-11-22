# herdr-claude

Claude Code sessions in [herdr](https://herdr.dev) instead of a terminal window each: one space
per project, one tab per session, and inside that tab a tile for every subagent and background
shell of the session, indexed by color and shape so you can tell who works for whom.

```
┌─────────────────────────────┬──────────────────────────────────┐
│                             │ ◉ roster                         │
│                             │ ● A survey hypr  · 2m · Read …   │
│   ◉ main Claude session     │   ▲ A1 check binds · <1m · Grep …│
│                             │ ● B run tests    · 4m · Bash …   │
│                             ├────────────────┬─────────────────┤
│                             │▌● A survey hypr│▌▲ A1 check bin… │
│                             │  ↖ ◉ main      │  ↖ ● A          │
│                             ├────────────────┴─────────────────┤
│                             │▌● B run tests   ↖ ◉ main         │
│                             ├──────────────────────────────────┤
│                             │▌$ B: cargo test                  │
└─────────────────────────────┴──────────────────────────────────┘
```

Claude Code runs its subagents (Agent tool, forks, workflow agents) inside the session's own
process, so herdr only ever sees one agent per pane. A hook records when subagents and background
shells start and stop; a watcher lays them out as tiles, and a viewer draws each tile from the
subagent's transcript or the shell's output file.

### The index

| | means | e.g. |
|---|---|---|
| code | place in the family tree: `A`, `B` … for the session's own agents, `A1`, `A2` for their children, then `A1a`, `A1a1` | `A2`: A's second child |
| color | the family: every agent the session starts gets one of 8 colors (Okabe-Ito, told apart with color blindness); its descendants keep it, a shade lighter per generation | all of A's line in orange |
| shape | the generation | `●` session agent · `▲` child · `◆` grandchild · `■` deeper · `$` shell · `◉` the session |

The family tree comes from Claude Code itself (`parentAgentId` in each subagent's meta file).

### The layout

The main Claude pane keeps the left part of the session's tab. The right column opens with the
roster (the whole tree, live: state, run time, current action) and takes a tile per agent:
session agents stack down the column, a child splits its parent's tile (to the right at odd
generations, down at even ones), and a background shell takes a strip at the bottom of its
owner's tile (the main pane's for the session's own shells). A tile that would get smaller than
6 rows x 30 columns isn't made; that agent or shell is in the roster only (`◌`).

Each tile has a header bar in its family color: index, task, whom it reports to (`↖ ● A`), run
time and current action; its name also sits on herdr's split border. A tile is only a view:
closing it (`q` in the tile) leaves the agent working, the roster lists it as `◌ hidden`, and it
stays closed when the agent wakes up again until you open it. When an agent's work ends its bar
turns grey and the tile closes a minute later (`k` keeps it); a shell's tile closes as soon as
the shell exits. Arrows and PgUp/PgDn scroll back, herdr's prefix+z zooms a tile. The roster
closes once nothing has run for a minute, and the main pane gets the whole tab back. New tabs
open only for new sessions.

The roster is interactive: ↑ ↓ (or j k, or the mouse wheel) select a row, Enter, space or a click
opens or closes its tile, `a` opens every hidden one, `h` hides them all. `prefix+a` brings the
same list up as a popup over the current tab (`claude-herdr-agents`, bound in the herdr config),
also when the roster itself is out of sight.

## Parts

Every project gets a herdr space of its own, named after it. A directory below the projects root
(`$CLAUDE_HERDR_PROJECTS`, default `~/Projects`) belongs to the project at the first level under
it; any other directory is a project of its own.

| File | What it does |
|---|---|
| `herdr-project-space` | Prints the space of a directory's project, creating it when missing; `--focus` switches herdr to it. `herdr-project-space [--focus] [DIR]` |
| `herdr-window` | The main herdr window: herdr keeps one session that every client shows, so one window is enough, the client attached longest. Prints its address; `--focus` brings it forward. The launchers here use it instead of attaching another client. |
| `herdr-open` | Opens a folder in the main herdr window: a shell in its project's space (a fresh space's first pane, a shell idling in that folder alone in its tab, or a new tab), then herdr shows it and the window comes to the front, whichever Hyprland workspace it is on. |
| `herdr-here` | `herdr-open` for the focused terminal's folder (for Omarchy's SUPER+CTRL+RETURN); a herdr terminal only opens when no herdr window exists |
| `claude-herdr` | Opens Claude in its project's space: in the space's only pane when that idles at a shell prompt in the directory (a fresh space), else in a new tab; then brings the herdr window forward, or opens one. `claude-herdr [--prompt TEXT] [--no-focus] [--space SDIR] [DIR] [-- CLAUDE_ARGS...]`; `$HOME` becomes the projects root, and `--space` puts Claude into another project's space while it runs in DIR. |
| `claude-herdr-move` | Moves Claude sessions from terminal windows into herdr: closes the window and resumes the conversation (`claude --resume`, same model and permission mode) in its project's space. Only sessions with nothing in flight (no turn, question, background shell or subagent) move; `--wait` waits for the others and moves each once it has been idle for 2 minutes; `--space DIR` puts them into DIR's project space. `claude-herdr-move` alone lists them. |
| `claude-herdr-tabs` | Claude Code hook (SubagentStart, SubagentStop, PostToolUse on Bash) for sessions in herdr: writes one event file per subagent start/stop and background shell start into `$XDG_RUNTIME_DIR/claude-herdr/events`. Returns at once outside herdr (~10 ms per Bash call). |
| `herdr_tiles.py` | The tile layout, run by the watcher: assigns codes, colors and shapes, places the tiles, keeps each session's roster (state in `$XDG_RUNTIME_DIR/claude-herdr/sessions/<id>/`). |
| `claude-herdr-view` | Draws the tiles (agent, shell, roster) and the grind loop tabs: a header bar in the family color over the newest lines of the work. |
| `claude-herdr-agents` | The roster of the focused tab's Claude session as a popup, for a herdr key: open or close agent and shell tiles without stopping their work. |
| `claude-herdr-subagents` | Watcher: for each Claude session in a herdr pane it reports the running subagents and background shells as pane tokens `$subs`, `$sa1k…5k` (index), `$sa1…5`, `$sa1do…5do` and `$sa_more`, and runs the tile layout (`herdr_tiles.py`). Tokens carry a 30 s TTL, renewed every 10 s while unchanged, so they vanish if the watcher stops. Grind loops (headless `claude -p` sessions named `<loop>-<n>`, one per iteration, run by a service) get a tab per loop in their project's space: the loop's current session live, beside the journal of the unit driving the loop (`<unit>.service` for sessions running as `<unit>-s<n>.service`); the tab closes once the loop has stopped, and one closed by hand stays closed while that loop runs. It also puts each space's folder under its name in the sidebar (`$path`, e.g. `~/Projects/herdr-claude`; a space named after a folder in the projects root shows that folder), and names tabs instead of leaving them numbered: after the Claude session's title where Claude runs, else after the tab's directory (like tmux's automatic-rename); a tab you rename yourself keeps its name. `--once` does one pass and prints what it sends. It reads the session data the bar widget already computes (`live.json`) while that is fresh, so it costs about 1 ms of CPU per second. |
| `claude-herdr-subagents.service` | systemd user unit for the watcher |
| `sidebar.toml` | The sidebar layouts that render the tokens: Claude rows with every subagent's index colored by family, space paths |

## Grind loops

A loop of headless Claude sessions gets a tab in its project's space when it keeps to this
naming; nothing else needs setting up:

- iteration *n* runs as a session named `<loop>-<n>` (`claude -p --name "<loop>-$n"`), without a
  terminal, from the project directory;
- for the journal pane: iteration *n* runs as the systemd unit `<driver>-s<n>`, started by the
  unit `<driver>` that runs the loop.

```bash
# the driver, started once:  systemd-run --user --unit=mygrind ./loop.sh
for ((n = 1; ; n++)); do
  systemd-run --user --wait --collect --unit="mygrind-s$n" --working-directory="$PWD" \
    claude -p --name "mygrind-$n" "…one iteration…"
done
```

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
         herdr-project-space herdr-open herdr-here herdr-window claude-herdr-agents; do   # herdr_tiles.py stays beside them
  ln -s "$PWD/$f" ~/.local/bin/
done
ln -s "$PWD/claude-herdr-subagents.service" ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now claude-herdr-subagents
cat sidebar.toml >> ~/.config/herdr/config.toml && herdr server reload-config
herdr integration install claude   # herdr resumes Claude sessions after a restart
```

Hooks for the agent tiles, in `~/.claude/settings.json` (new sessions pick them up):

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

and in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+a"
type = "popup"
command = "claude-herdr-agents"
description = "Claude agents: open or close tiles"
width = "70%"
height = "60%"
```

And so that a plain `herdr` belongs to the main herdr window, in `~/.bashrc`: inside herdr (where a nested herdr is refused) it switches to the folder's space; in a terminal outside, the folder gets a shell in the main window (`herdr-open`), that window comes to the front and the terminal closes, since its shell lives on there (it stays in tmux, over SSH or with jobs running). Only without any herdr window does herdr attach in that terminal:

```bash
herdr() {
  if (($# == 0)) && command -v herdr-open > /dev/null; then
    if [[ -n ${HERDR_ENV:-} ]]; then
      [[ -n $(herdr-project-space --focus "$PWD") ]] || echo "herdr: no project space for $PWD" >&2
      return
    fi
    herdr-open "$PWD" > /dev/null
    case $? in
      0)
        if [[ -z $(jobs -p) ]] && hyprctl clients -j 2> /dev/null |
          jq -e --argjson p "$PPID" 'any(.[]; .pid == $p)' > /dev/null; then
          exit
        fi
        return
        ;;
      3) ;;  # no herdr window yet: start one here
      *) return ;;
    esac
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
