"""Agent tiles: the subagents and background shells of a Claude session in herdr, laid out
in the session's own tab.

claude-herdr-tabs (the Claude Code hook) drops event files into $STATE/events; the
watcher calls tick() every poll. Per session:

  * every subagent gets an index: a code giving its place in the family tree
    (A, B … for the session's own agents, A1, A2 for their children, then A1a, A1a1),
    a color for its family (the session agent it descends from; lighter per
    generation) and a shape for its generation (● ▲ ◆ ■). Shells are $ in their
    owner's color, the session itself ◉.
  * the main Claude pane keeps the left part of the tab. The right column starts with
    the roster (the whole tree, live) and holds a tile per agent: session agents stack
    down the column, a child splits its parent's tile (to the right at odd generations,
    down at even ones), and a shell takes a strip at the bottom of its owner's tile
    (the main pane for the session's own shells). A tile that would get smaller than
    MIN_ROWS x MIN_COLS isn't made: that agent is in the roster only.
  * claude-herdr-view draws the tiles: a header bar in the family color with the
    agent's code and the one it reports to, its work below. A tile closes itself a
    while after its work ends; the roster goes once nothing has run for ROSTER_IDLE s.

State lives in $STATE/sessions/<session id>/: layout.json (codes, tiles), roster.json
(what the roster tile shows), done/<agent id> (stop markers the views watch).
"""
import glob
import json
import os
import re
import subprocess
import time

HERE = os.path.dirname(os.path.realpath(__file__))
STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "claude-herdr")
EVENTS = os.path.join(STATE, "events")
SESSIONS = os.path.join(STATE, "sessions")
CONFIG = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
VIEW = os.path.join(HERE, "claude-herdr-view")

# Okabe-Ito: told apart with every common kind of color blindness
PALETTE = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#88CCEE"]
SHAPES = {1: "●", 2: "▲", 3: "◆"}
DEEP_SHAPE = "■"
MAIN_SHAPE, SHELL_SHAPE = "◉", "$"
MIN_ROWS, MIN_COLS = 6, 30
MAIN_KEEP = 0.55      # share of the tab the main pane keeps when the column opens
ROSTER_KEEP = 0.3     # share of the column the roster keeps above the first agent tile
SHELL_OWNER_KEEP = 0.7
ROSTER_IDLE = 60      # s without running agents or open tiles before the roster closes
META_WAIT = 10        # s an agent-start event waits for the agent's meta file


def log(msg):
    print(f"tiles: {msg}", flush=True)


# --- herdr ---------------------------------------------------------------------

def herdr(sock, *args):
    env = dict(os.environ, HERDR_SOCKET_PATH=sock) if sock else None
    r = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=10, env=env)
    try:
        resp = json.loads(r.stdout)
    except ValueError:
        return None
    if resp.get("error"):
        log(f"herdr {' '.join(args[:2])}: {resp['error'].get('message')}")
        return None
    return resp.get("result") or {}


def rects(sock, pane):
    """pane id -> rect for every pane in the tab of `pane`."""
    lay = (herdr(sock, "pane", "layout", "--pane", pane) or {}).get("layout") or {}
    return {p["pane_id"]: p["rect"] for p in lay.get("panes", []) if "rect" in p}


def fits(rect, direction, keep):
    if not rect:
        return False
    if direction == "down":
        a = int(rect["height"] * keep)
        return a >= MIN_ROWS and rect["height"] - a - 1 >= MIN_ROWS
    a = int(rect["width"] * keep)
    return a >= MIN_COLS and rect["width"] - a - 1 >= MIN_COLS


def split(sock, pane, direction, keep, cwd):
    r = herdr(sock, "pane", "split", pane, "--direction", direction, "--ratio", f"{keep:.2f}",
              "--cwd", cwd or os.path.expanduser("~"), "--no-focus")
    return ((r or {}).get("pane") or {}).get("pane_id")


def start_view(sock, pane, spec, label):
    path = os.path.join(STATE, f"view.{time.time_ns()}.json")
    with open(path, "w") as f:
        json.dump(spec, f)
    herdr(sock, "pane", "run", pane, f"exec {VIEW} {path}")
    herdr(sock, "pane", "rename", pane, label[:40])


# --- index ---------------------------------------------------------------------

def family_letters(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def child_code(parent_code, parent_depth, n):
    """n-th child (1-based): digits under letter generations, letters under digit ones."""
    if parent_depth % 2:  # A -> A1, A1a -> A1a1
        return f"{parent_code}{n}"
    return parent_code + family_letters(n - 1).lower()  # A1 -> A1a


def color(family, depth):
    base = PALETTE[family % len(PALETTE)]
    r, g, b = (int(base[i:i + 2], 16) for i in (1, 3, 5))
    mix = min(0.6, 0.2 * (depth - 1))
    r, g, b = (round(c + (255 - c) * mix) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def shape(depth):
    return SHAPES.get(depth, DEEP_SHAPE)


# --- sessions ------------------------------------------------------------------

class Session:
    def __init__(self, sid):
        self.sid = sid
        self.dir = os.path.join(SESSIONS, sid)
        os.makedirs(os.path.join(self.dir, "done"), exist_ok=True)
        self.d = {"main": None, "sock": "", "cpid": 0, "cwd": None, "transcript": None, "roster": None,
                  "agents": {}, "shells": {}, "families": 0, "children": {}, "idle_since": time.time()}
        try:
            with open(os.path.join(self.dir, "layout.json")) as f:
                self.d.update(json.load(f))
        except (OSError, ValueError):
            pass
        self.d["idle_since"] = time.time()  # a restart doesn't count as idle time
        self.roster_json = None

    def save(self):
        tmp = os.path.join(self.dir, "layout.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.d, f)
        os.replace(tmp, os.path.join(self.dir, "layout.json"))

    # where things go ------------------------------------------------------------

    def ensure_column(self, alive):
        """The right column (roster at its top); False when there's no room for it."""
        d = self.d
        if d["roster"] in alive:
            return True
        main = d["main"]
        r = rects(d["sock"], main).get(main)
        if not fits(r, "right", MAIN_KEEP):
            return False
        pane = split(d["sock"], main, "right", MAIN_KEEP, d["cwd"])
        if not pane:
            return False
        d["roster"] = pane
        start_view(d["sock"], pane, {"mode": "roster", "roster": os.path.join(self.dir, "roster.json"),
                                     "pid": d["cpid"]}, f"{MAIN_SHAPE} roster")
        alive.add(pane)
        return True

    def place_agent(self, a, alive):
        d = self.d
        if not self.ensure_column(alive):
            return None
        lay = rects(d["sock"], d["roster"])
        parent = d["agents"].get(a.get("parent") or "")
        if parent and parent.get("tile") in alive:
            first = "right" if parent["depth"] % 2 else "down"
            for direction in (first, "down" if first == "right" else "right"):
                if fits(lay.get(parent["tile"]), direction, 0.5):
                    return split(d["sock"], parent["tile"], direction, 0.5, d["cwd"])
            return None
        # A session agent (or a child whose parent has no tile): stack down the column,
        # below the roster at first, then by halving the tallest agent tile.
        tiles = [x["tile"] for x in d["agents"].values() if x.get("tile") in alive and x["depth"] == 1]
        if not tiles:
            if fits(lay.get(d["roster"]), "down", ROSTER_KEEP):
                return split(d["sock"], d["roster"], "down", ROSTER_KEEP, d["cwd"])
            return None
        tallest = max(tiles, key=lambda p: (lay.get(p) or {}).get("height", 0))
        if fits(lay.get(tallest), "down", 0.5):
            return split(d["sock"], tallest, "down", 0.5, d["cwd"])
        return None

    def place_shell(self, owner_pane, alive):
        d = self.d
        lay = rects(d["sock"], owner_pane)
        strips = [s["tile"] for s in d["shells"].values()
                  if s.get("tile") in alive and s.get("under") == owner_pane]
        if strips:
            last = strips[-1]
            if fits(lay.get(last), "right", 0.5):
                return split(d["sock"], last, "right", 0.5, d["cwd"])
            return None
        if fits(lay.get(owner_pane), "down", SHELL_OWNER_KEEP):
            return split(d["sock"], owner_pane, "down", SHELL_OWNER_KEEP, d["cwd"])
        return None

    # events ---------------------------------------------------------------------

    def agent_start(self, ev, alive):
        d, inp = self.d, ev["input"]
        aid = inp.get("agent_id")
        if not aid:
            return True
        tp = inp.get("transcript_path") or d["transcript"] or ""
        at = os.path.join(tp[:-6] if tp.endswith(".jsonl") else tp, "subagents", f"agent-{aid}.jsonl")
        meta_path = at[:-6] + ".meta.json"
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            if time.time() - ev["_at"] < META_WAIT:
                return False  # try again next poll
            meta = {}
        a = d["agents"].get(aid)
        if a is None:
            parent = d["agents"].get(meta.get("parentAgentId") or "")
            if parent:
                depth, family = parent["depth"] + 1, parent["family"]
                d["children"][parent["code"]] = d["children"].get(parent["code"], 0) + 1
                code = child_code(parent["code"], parent["depth"], d["children"][parent["code"]])
            else:
                depth, family = 1, d["families"]
                d["families"] += 1
                code = family_letters(family)
            a = d["agents"][aid] = {
                "code": code, "depth": depth, "family": family, "parent": parent and meta.get("parentAgentId"),
                "type": inp.get("agent_type") or meta.get("agentType") or "agent",
                "description": meta.get("description") or "", "fork": bool(meta.get("isFork")),
                "transcript": at, "started": time.time(), "tile": None, "done": None}
        a["done"] = None  # (again) at work
        try:
            os.unlink(os.path.join(self.dir, "done", aid))
        except OSError:
            pass
        if a.get("tile") in alive:
            return True  # woke up again; its view goes on
        pane = self.place_agent(a, alive)
        if pane:
            a["tile"] = pane
            alive.add(pane)
            p = d["agents"].get(a.get("parent") or "")
            boss = ({"code": p["code"], "shape": shape(p["depth"]), "color": color(p["family"], p["depth"])}
                    if p else {"code": "main", "shape": MAIN_SHAPE, "color": None})
            start_view(d["sock"], pane, {
                "mode": "agent", "transcript": at, "meta": meta_path, "done": os.path.join(self.dir, "done", aid),
                "pid": d["cpid"], "type": a["type"], "description": a["description"],
                "code": a["code"], "shape": shape(a["depth"]), "color": color(a["family"], a["depth"]),
                "boss": boss, "started": a["started"]}, f"{shape(a['depth'])} {a['code']} {a['description']}")
        return True

    def agent_stop(self, ev, alive):
        aid = ev["input"].get("agent_id")
        a = self.d["agents"].get(aid or "")
        if a:
            a["done"] = time.time()
            open(os.path.join(self.dir, "done", aid), "w").close()
        return True

    def shell(self, ev, alive):
        d, inp = self.d, ev["input"]
        tid = (inp.get("tool_response") or {}).get("backgroundTaskId")
        if not tid or tid in d["shells"]:
            return True
        hits = (glob.glob(f"/tmp/claude-{os.getuid()}/*/{self.sid}/tasks/{tid}.output")
                or glob.glob(f"/tmp/claude-{os.getuid()}/*/*/tasks/{tid}.output"))
        if not hits:
            return time.time() - ev["_at"] > META_WAIT  # the file shows up a moment later
        owner = d["agents"].get(inp.get("agent_id") or "")
        under = owner["tile"] if owner and owner.get("tile") in alive else d["main"]
        if owner:
            code, col = owner["code"], color(owner["family"], owner["depth"])
        else:
            code, col = "main", None
        ti = inp.get("tool_input") or {}
        sh = d["shells"][tid] = {"owner": code, "description": ti.get("description") or "",
                                  "tile": None, "under": under, "started": time.time()}
        pane = self.place_shell(under, alive)
        if pane:
            sh["tile"] = pane
            alive.add(pane)
            start_view(d["sock"], pane, {
                "mode": "shell", "output": hits[0], "pid": d["cpid"], "description": sh["description"],
                "command": ti.get("command") or "", "owner": code, "id": tid, "color": col,
                "shape": SHELL_SHAPE}, f"{SHELL_SHAPE} {code}: {sh['description'] or tid}")
        return True

    # roster -----------------------------------------------------------------------

    def roster(self, live, alive, now):
        """Write roster.json; close the roster when nothing has run for a while."""
        d = self.d
        running = {a.get("id"): a for a in (live or {}).get("agents", []) if isinstance(a, dict)}
        rows = []

        def walk(parent, depth):
            kids = [(aid, a) for aid, a in d["agents"].items() if (a.get("parent") or None) == parent]
            for aid, a in sorted(kids, key=lambda x: x[1]["started"]):
                r = running.get(aid) or {}
                act = r.get("action") or {}
                # Running from its start event until its stop event; an agent with neither a
                # tile nor a place in sessions.sh's list after a while is over too.
                if a.get("done"):
                    state = "done"
                elif aid in running or a.get("tile") in alive or now - a["started"] < 20:
                    state = "run"
                else:
                    state = "done"
                rows.append({"code": a["code"], "shape": shape(a["depth"]), "color": color(a["family"], a["depth"]),
                             "depth": a["depth"], "description": a["description"] or a["type"],
                             "started": (r.get("startedAt") or a["started"] * 1000) / 1000, "state": state,
                             "tile": a.get("tile") in alive, "fork": a.get("fork"),
                             "action": " ".join(str(x) for x in (act.get("tool"), act.get("detail")) if x)})
                for sid_, s in d["shells"].items():
                    if s["owner"] == a["code"]:
                        rows.append({"code": s["owner"], "shape": SHELL_SHAPE, "color": color(a["family"], a["depth"]),
                                     "depth": a["depth"] + 1, "description": s["description"] or sid_,
                                     "started": s["started"], "state": "run" if s.get("tile") in alive else "done",
                                     "tile": s.get("tile") in alive, "action": ""})
                walk(aid, depth + 1)

        walk(None, 1)
        for sid_, s in d["shells"].items():
            if s["owner"] == "main":
                rows.append({"code": "main", "shape": SHELL_SHAPE, "color": None, "depth": 1,
                             "description": s["description"] or sid_, "started": s["started"],
                             "state": "run" if s.get("tile") in alive else "done", "tile": s.get("tile") in alive,
                             "action": ""})
        busy = any(r["state"] == "run" for r in rows) or any(
            x.get("tile") in alive for x in list(d["agents"].values()) + list(d["shells"].values()))
        if busy:
            d["idle_since"] = now
        if d["roster"] in alive and not busy and now - d["idle_since"] > ROSTER_IDLE:
            herdr(d["sock"], "pane", "close", d["roster"])
            d["roster"] = None
            d["agents"], d["shells"], d["families"], d["children"] = {}, {}, 0, {}
            return True
        doc = json.dumps({"rows": rows, "session": d["main"]}, sort_keys=True)
        if doc != self.roster_json:
            self.roster_json = doc
            tmp = os.path.join(self.dir, "roster.json.tmp")
            with open(tmp, "w") as f:
                f.write(doc)
            os.replace(tmp, os.path.join(self.dir, "roster.json"))
        return False


_sessions = {}


def session(sid):
    if sid not in _sessions:
        _sessions[sid] = Session(sid)
    return _sessions[sid]


def load_all():
    """Sessions with tiles from before a watcher restart."""
    for path in glob.glob(os.path.join(SESSIONS, "*", "layout.json")):
        session(os.path.basename(os.path.dirname(path)))


def active():
    """Whether some session has tiles, or events are waiting."""
    return any(s.d.get("roster") for s in _sessions.values()) or bool(glob.glob(os.path.join(EVENTS, "*.json")))


def codes(sid):
    """agent id -> (shape code, depth) for the sidebar."""
    s = _sessions.get(sid)
    if not s:
        return {}
    return {aid: (f"{shape(a['depth'])} {a['code']}", a["depth"]) for aid, a in s.d["agents"].items()}


def tick(alive_by_sock, live_by_sid):
    """Apply new events, keep rosters current. `alive_by_sock`: socket -> pane ids herdr
    has; `live_by_sid`: sessions.sh entries by session id."""
    os.makedirs(EVENTS, exist_ok=True)
    now = time.time()
    touched = set()
    for path in sorted(glob.glob(os.path.join(EVENTS, "*.json"))):
        try:
            with open(path) as f:
                ev = json.load(f)
        except (OSError, ValueError):
            os.unlink(path)
            continue
        m = re.match(r"(\d+)-", os.path.basename(path))
        ev["_at"] = int(m.group(1)) / 1e9 if m else now
        inp = ev.get("input") or {}
        sid = inp.get("session_id")
        if not sid or not ev.get("sock"):
            os.unlink(path)
            continue
        s = session(sid)
        d = s.d
        d["main"], d["cpid"] = ev.get("pane") or d["main"], ev.get("cpid") or d["cpid"]
        d["sock"] = ev["sock"]
        d["cwd"] = inp.get("cwd") or d["cwd"]
        d["transcript"] = d["transcript"] or inp.get("transcript_path")
        alive = alive_by_sock.get(d["sock"])
        if alive is None:
            continue  # this herdr server wasn't polled yet
        handler = {"agent-start": s.agent_start, "agent-stop": s.agent_stop, "shell": s.shell}.get(ev.get("event"))
        try:
            finished = handler(ev, alive) if handler else True
        except (OSError, subprocess.SubprocessError, KeyError, TypeError) as e:
            log(f"{ev.get('event')}: {e!r}")
            finished = True
        if finished:
            os.unlink(path)
        touched.add(sid)
    for sid in list(_sessions):
        s = _sessions[sid]
        alive = alive_by_sock.get(s.d["sock"])
        if alive is None or (s.d["main"] not in alive and not s.d["roster"]):
            continue
        if s.roster(live_by_sid.get(sid), alive, now) or sid in touched:
            s.save()
    return touched


def sockets():
    """The herdr sockets sessions with tiles talk to."""
    return {s.d["sock"] for s in _sessions.values() if s.d.get("sock")} | {
        e.get("sock") for e in _pending_socks() if e.get("sock")}


def _pending_socks():
    out = []
    for path in glob.glob(os.path.join(EVENTS, "*.json")):
        try:
            with open(path) as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            pass
    return out
