#!/usr/bin/env python3
"""Your recent Claude Code work, from the history Claude Code keeps on this computer.

  work.py threads [--days 7] [--here]   sessions by project, with the first and last thing you asked
  work.py standup                       since the start of your last workday: sessions, plus your own commits
  work.py search WORDS... [--days N]    sessions where you asked about all of these words, newest first
  work.py brag [--days 30]              your commits and sessions over a longer stretch, for a review or a 1:1
  work.py export SESSION_ID             one session's conversation, your messages and Claude's replies, to write up
  work.py keep [--set DAYS]             how long Claude Code keeps transcripts; --set changes it in settings.json

  Add --codex before the command (work.py --codex threads) to read Codex's history in ~/.codex instead.

Reads ~/.claude/history.jsonl (the prompts you typed) and, for the sessions it lists, the title line of each
one's transcript in ~/.claude/projects; export reads one whole transcript, and keep reads cleanupPeriodDays from
~/.claude/settings.json. It runs read-only git commands in those sessions' folders: `rev-parse` to find each repo,
and for standup and brag `config user.email`, `branch`, `status` and `log`, all with --no-optional-locks so git
writes nothing. It makes no network calls. It writes one file, only for `keep --set`: ~/.claude/settings.json,
after saving a copy of it as settings.json.shabash-backup.
"""
import argparse, collections, datetime, glob, json, os, shlex, subprocess, tempfile

HOME = os.path.expanduser("~/.claude")
CODEX = os.path.expanduser("~/.codex")
AGENT = {"name": "claude"}  # main() sets "codex" for --codex


def codex():
    return AGENT["name"] == "codex"


def no_history():
    return "No Codex history on this computer (~/.codex/history.jsonl)." if codex() else \
        "No Claude Code history on this computer (~/.claude/history.jsonl)."


def git(folder, *args):
    """git's output in a folder, or "" when it isn't a repo or git doesn't answer."""
    if not os.path.isdir(folder or ""):
        return ""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", folder, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


_roots = {}
def project_of(folder):
    """The repo a folder belongs to, so sessions in subfolders land under one project."""
    if folder not in _roots:
        _roots[folder] = git(folder, "rev-parse", "--show-toplevel") or folder
    return _roots[folder]


def session_titles(ids):
    """{session id: the title the agent gave it} for these sessions, and which of them can still be resumed.
    Opens only those sessions' transcripts (Codex: its thread-name index), and only to find their titles."""
    titles, kept = {}, set()
    ids = set(ids)
    if codex():
        kept = {sid for sid in ids if transcript_path(sid)}
        try:
            with open(os.path.join(CODEX, "session_index.jsonl"), errors="ignore") as fh:
                for line in fh:
                    row = json.loads(line)
                    if row.get("id") in ids and row.get("thread_name"):
                        titles[row["id"]] = row["thread_name"]
        except (OSError, ValueError):
            pass
        return titles, kept
    for sid in ids:
        for path in glob.glob(os.path.join(HOME, "projects", "*", glob.escape(sid) + ".jsonl")):
            kept.add(sid)
            try:
                with open(path, errors="ignore") as fh:
                    for line in fh:
                        if '"custom-title"' not in line and '"ai-title"' not in line:
                            continue
                        row = json.loads(line)
                        titles[sid] = row.get("customTitle") or row.get("aiTitle") or titles.get(sid)
            except (OSError, ValueError):
                pass
    return titles, kept


_codex_folders = {}
def codex_folder(sid):
    """The folder a Codex session ran in, from the first line of its transcript."""
    if sid not in _codex_folders:
        path, folder = transcript_path(sid), None
        try:
            with open(path or "", errors="ignore") as fh:
                folder = (json.loads(fh.readline()).get("payload") or {}).get("cwd")
        except (OSError, ValueError):
            pass
        _codex_folders[sid] = folder
    return _codex_folders[sid]


def json_lines(path):
    """Each line of a JSONL file that parses, skipping the rest."""
    with open(path, errors="ignore") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def number(v):
    """A timestamp field as a number, or 0 when it's missing or not a number."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def history_rows():
    """(session id, time in ms, prompt, folder) for every prompt in the agent's own history file."""
    path = os.path.join(CODEX if codex() else HOME, "history.jsonl")
    for row in json_lines(path):
        if not isinstance(row, dict):
            continue
        if codex():
            sid, ms, ask, folder = row.get("session_id"), number(row.get("ts")) * 1000, row.get("text"), None
        else:
            sid, ms, ask, folder = row.get("sessionId"), number(row.get("timestamp")), row.get("display"), row.get("project")
        if isinstance(sid, str) and isinstance(ask, str):
            yield sid, ms, ask, folder if isinstance(folder, str) else None


def sessions_since(start):
    """Sessions with a prompt after `start` (a datetime), oldest first: {id: {folder, first, last, asks}}."""
    found = collections.OrderedDict()
    if not os.path.exists(os.path.join(CODEX if codex() else HOME, "history.jsonl")):
        return None
    cutoff = start.timestamp() * 1000
    for sid, ms, ask, folder in history_rows():
        ask = " ".join(ask.split())
        if not sid or ms < cutoff or not ask or (ask.startswith("/") and " " not in ask):
            continue  # a bare slash command says nothing about the work
        s = found.setdefault(sid, {"folder": folder, "first": ms, "last": ms, "asks": []})
        s["last"] = max(s["last"], ms)
        s["asks"].append(ask)
    if codex():
        for sid, s in found.items():
            s["folder"] = codex_folder(sid)
    return found


def days_ago(days):
    return datetime.datetime.now() - datetime.timedelta(days=days)


def by_project(found, only=None):
    """[(project folder, [(id, session)] newest first)], most recently active project first."""
    groups = collections.defaultdict(list)
    for sid, s in found.items():
        root = project_of(s["folder"])
        if only is None or root == only:
            groups[root].append((sid, s))
    for items in groups.values():
        items.sort(key=lambda kv: -kv[1]["last"])
    return sorted(groups.items(), key=lambda kv: -kv[1][0][1]["last"])


def stamp(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%a %d %b %H:%M")


def cut(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


def print_session(sid, s, titles, kept, resume):
    print(f"- {stamp(s['last'])} · {titles.get(sid) or cut(s['asks'][0], 80)} · {len(s['asks'])} prompts")
    print(f"  first ask: {cut(s['asks'][0], 200)}")
    if len(s["asks"]) > 1:
        print(f"  last ask: {cut(s['asks'][-1], 240)}")
    if resume:
        tool = "codex resume" if codex() else "claude --resume"
        print(f"  resume: cd {shlex.quote(s['folder'] or '.')} && {tool} {shlex.quote(sid)}" if sid in kept else
              "  can't resume: the transcript is no longer on this computer")


def threads(days, here):
    found = sessions_since(days_ago(days))
    if found is None:
        return print(no_history())
    groups = by_project(found, project_of(os.getcwd()) if here else None)
    if not groups:
        return print(f"No Claude Code sessions in the last {days} days" + (" in this project." if here else "."))
    titles, kept = session_titles(sid for _, items in groups for sid, _ in items[:12])
    print(f"# {'Codex' if codex() else 'Claude Code'} sessions, last {days} days\n")
    for root, items in groups:
        print(f"## {os.path.basename(root) or root}  ({root})")
        for sid, s in items[:12]:
            print_session(sid, s, titles, kept, resume=True)
        print()


def last_workday_start(now):
    """Midnight at the start of the previous workday: Friday's on a Monday (or the weekend), else yesterday's."""
    back = {0: 3, 6: 2, 5: 1}.get(now.weekday(), 1)
    return (now - datetime.timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)


def print_git(root, start, limit):
    """The branch, uncommitted files and your own commits (by the email in this repo's git settings) since `start`."""
    branch = git(root, "branch", "--show-current")
    if branch:
        changed = len(git(root, "status", "--porcelain").splitlines())
        print(f"branch: {branch}" + (f" · {changed} files not committed" if changed else ""))
    me = git(root, "config", "user.email")
    if not me:
        return print("commits: none shown, this repo has no git email set") if branch else None
    log = git(root, "log", "--no-merges", f"--since={start:%Y-%m-%d %H:%M}", f"--author={me}", "--format=%h %ad %s", "--date=short")
    lines = log.splitlines()
    for c in lines[:limit]:
        print(f"commit: {c}")
    if len(lines) > limit:
        print(f"commit: … and {len(lines) - limit} more")


def report(start, heading, git_limit, per_project):
    """Sessions since `start` by project, each project with its git state and your commits."""
    found = sessions_since(start)
    if found is None:
        return print(no_history())
    groups = by_project(found)
    titles, kept = session_titles(sid for _, items in groups for sid, _ in items[:per_project])
    print(heading + "\n")
    if not groups:
        print("No Claude Code sessions since then.")
    for root, items in groups:
        print(f"## {os.path.basename(root) or root}")
        print_git(root, start, git_limit)
        for sid, s in items[:per_project]:
            print_session(sid, s, titles, kept, resume=False)
        print()


def standup():
    now = datetime.datetime.now()
    start = last_workday_start(now)
    report(start, f"# Since {start:%A %d %B} (today is {now:%A})", 15, 10)


def brag(days):
    start = days_ago(days).replace(hour=0, minute=0, second=0, microsecond=0)
    report(start, f"# Since {start:%d %B %Y} ({days} days)", 60, 20)


def search(words, days):
    """Sessions with a prompt containing every word, newest first, with the prompt that matched."""
    found = sessions_since(days_ago(days))
    if found is None:
        return print(no_history())
    want = [w.lower() for w in words]
    hits = [(sid, s, ask) for sid, s in found.items()
            for ask in [next((a for a in reversed(s["asks"]) if all(w in a.lower() for w in want)), None)] if ask]
    hits.sort(key=lambda h: -h[1]["last"])
    if not hits:
        return print(f"No session in the last {days} days has a prompt with all of: {' '.join(words)}")
    titles, kept = session_titles(sid for sid, _, _ in hits[:15])
    print(f"# Sessions matching: {' '.join(words)} ({len(hits)} found, newest 15 shown)\n")
    for sid, s, ask in hits[:15]:
        print(f"## {os.path.basename(project_of(s['folder'])) or s['folder']}")
        print(f"  matched: {cut(ask, 240)}")
        print_session(sid, s, titles, kept, resume=True)
        print()


def transcript_path(sid):
    """The transcript file for a session id or a unique prefix of one, or None."""
    if not sid or not all(c.isalnum() or c == "-" for c in sid):
        return None  # ids are letters, digits and dashes; anything else isn't one
    if codex():
        found = glob.glob(os.path.join(CODEX, "sessions", "*", "*", "*", f"rollout-*-{glob.escape(sid)}*.jsonl")) + \
            glob.glob(os.path.join(CODEX, "archived_sessions", f"rollout-*-{glob.escape(sid)}*.jsonl"))
        return found[0] if len(found) == 1 else None
    found = glob.glob(os.path.join(HOME, "projects", "*", glob.escape(sid) + "*.jsonl"))
    return found[0] if len(found) == 1 else None


def turn(row):
    """(who, row in Claude Code's shape) for a conversation line of either agent, or (None, None)."""
    if not isinstance(row, dict):
        return None, None
    if not codex():
        if row.get("type") in ("user", "assistant") and not row.get("isMeta") and not row.get("isSidechain"):
            return ("You" if row["type"] == "user" else "Claude"), row
        return None, None
    p = row.get("payload") or {}
    if row.get("type") != "response_item":
        return None, None
    if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
        blocks = [{"type": "text", "text": b.get("text", "")} for b in p.get("content") or []]
        return ("You" if p["role"] == "user" else "Codex"), {"message": {"content": blocks}, "timestamp": row.get("timestamp")}
    if p.get("type") in ("custom_tool_call", "function_call"):
        block = {"type": "tool_use", "name": p.get("name"), "input": {}}
        return "Codex", {"message": {"content": [block]}, "timestamp": row.get("timestamp")}
    return None, None


def message_text(row):
    """What a transcript line said, as plain text: your words, the agent's words, and one line per tool it used."""
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind == "tool_use":
            args = block.get("input") or {}
            what = args.get("description") or args.get("file_path") or args.get("command") or args.get("pattern") or ""
            what = cut(" ".join(str(what).split()), 100)
            parts.append(f"[used {block.get('name')}" + (f": {what}]" if what else "]"))
    return "\n".join(p for p in parts if p.strip())


def export(sid, limit):
    path = transcript_path(sid)
    if not path:
        return print(f"No single transcript matches {sid}. Use the full session id from search or threads.")
    sid = os.path.basename(path)[:-len(".jsonl")]
    if codex():
        sid = sid[-36:]  # rollout-<time>-<session id>.jsonl
    titles, _ = session_titles([sid])
    out, total, folder, first, last = [], 0, None, None, None
    for row in json_lines(path):
        who, row = turn(row)
        if not who:
            continue
        text = message_text(row).strip()
        if not text or text.startswith("<"):
            continue  # tool results and system notes come back as user lines; they aren't the conversation
        folder, first, last = folder or row.get("cwd"), first or row.get("timestamp"), row.get("timestamp")
        block = f"### {who}\n{cut(text, 4000)}\n"
        if total + len(block) > limit:
            out.append(f"… the rest is cut here, after {total} characters (--max-chars raises it)")
            break
        out.append(block)
        total += len(block)
    folder = folder or (codex_folder(sid) if codex() else None)
    print(f"# {titles.get(sid) or 'Session'} ({sid})\nfolder: {folder}\nfrom {first} to {last}\n")
    print("\n".join(out))


SETTINGS = os.path.join(HOME, "settings.json")


def keep(days):
    """How long transcripts are kept and what's been lost; with `days`, set cleanupPeriodDays after a backup."""
    if codex():
        return print("keep is for Claude Code, which deletes transcripts after 30 days by default. Codex keeps its "
                     "sessions in ~/.codex/sessions until you archive or delete them.")
    try:
        with open(SETTINGS) as fh:
            settings = json.load(fh)
    except FileNotFoundError:
        settings = {}
    except ValueError:
        return print(f"{SETTINGS} isn't valid JSON, so this leaves it alone.")
    if not isinstance(settings, dict):
        return print(f"{SETTINGS} doesn't hold a settings object, so this leaves it alone.")
    current = settings.get("cleanupPeriodDays")
    if days is not None:
        if days < 1:
            return print("Use a number of days of 1 or more.")
        target, backup = os.path.realpath(SETTINGS), SETTINGS + ".shabash-backup"
        kept_backup = os.path.exists(backup)
        if os.path.exists(target) and not kept_backup:  # the first backup is the file before Shabash ever changed it
            with open(target, "rb") as src, open(backup, "wb") as dst:
                dst.write(src.read())
        settings["cleanupPeriodDays"] = days
        os.makedirs(os.path.dirname(target), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".settings-")
        with os.fdopen(fd, "w") as fh:  # written whole, then swapped in, so a crash never leaves half a file
            json.dump(settings, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        if os.path.exists(target):
            os.chmod(tmp, os.stat(target).st_mode & 0o777)
        os.replace(tmp, target)
        was = current if current is not None else "not set (30)"
        note = f"\nThe file as it was before Shabash first changed it is at {backup}" if os.path.exists(backup) else ""
        return print(f"cleanupPeriodDays: {was} -> {days} in {SETTINGS}{note}")
    kept = glob.glob(os.path.join(HOME, "projects", "*", "*.jsonl"))
    found = sessions_since(datetime.datetime(1971, 1, 1)) or {}
    lost = [s for sid, s in found.items() if not transcript_path(sid)]
    oldest = min((os.path.getmtime(p) for p in kept), default=None)
    print(f"cleanupPeriodDays: {current if current is not None else 'not set, so Claude Code uses its 30-day default'}")
    print(f"transcripts on this computer: {len(kept)}, {sum(os.path.getsize(p) for p in kept) // 1_000_000} MB")
    if oldest:
        print(f"oldest kept transcript last changed: {datetime.datetime.fromtimestamp(oldest):%d %B %Y}")
    print(f"sessions in your prompt history whose transcript is gone: {len(lost)} of {len(found)}")
    if lost:
        print(f"newest of those: {stamp(max(s['last'] for s in lost))}")


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("--codex", action="store_true", help="read Codex's history (~/.codex) instead of Claude Code's")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("threads")
    t.add_argument("--days", type=int, default=7)
    t.add_argument("--here", action="store_true", help="only the project you're in")
    sub.add_parser("standup")
    s = sub.add_parser("search")
    s.add_argument("words", nargs="+")
    s.add_argument("--days", type=int, default=365)
    b = sub.add_parser("brag")
    b.add_argument("--days", type=int, default=30)
    e = sub.add_parser("export")
    e.add_argument("session")
    e.add_argument("--max-chars", type=int, default=60000)
    k = sub.add_parser("keep")
    k.add_argument("--set", type=int, dest="days")
    a = ap.parse_args()
    AGENT["name"] = "codex" if a.codex else "claude"
    if a.cmd == "threads": threads(a.days, a.here)
    elif a.cmd == "standup": standup()
    elif a.cmd == "search": search(a.words, a.days)
    elif a.cmd == "brag": brag(a.days)
    elif a.cmd == "export": export(a.session, a.max_chars)
    else: keep(a.days)


if __name__ == "__main__":
    main()
