# Shabash: standup, brag doc and session search for Claude Code and Codex

Your daily standup, your brag doc for a review, and any old session found again, written from the work you already did in Claude Code or Codex. It also tells you how many sessions Claude Code has already deleted, and stops it deleting more (it can't bring back ones already gone). Made by [Shabash](https://shabash.dev/?utm_source=github&utm_medium=readme&utm_campaign=shabash_plugin), an app for teams that use Claude Code.

- `/shabash:standup` writes your standup from your sessions and your own commits since the start of your last workday (all of Friday, on a Monday or a weekend), ready to paste into Slack.
- `/shabash:search` finds an old session from words you typed in it, like a feature or an error, with the command to resume it. It looks through the prompts you typed in the last year.
- `/shabash:brag` writes your brag doc from your sessions and commits over the last 30 days (or a quarter), for a performance review or a 1:1.
- `/shabash:export` turns one session into a clean document: a write-up of what was decided and changed, or the whole conversation without the tool output.
- `/shabash:threads` lists what you worked on in the last 7 days, by project, with where each piece of work stopped and the command to resume it.
- `/shabash:keep` shows how long Claude Code keeps your transcripts (30 days unless you've changed it) and how many are already gone. Only if you say yes, it raises the limit.

You can also ask in your own words, like "what was I working on?", "find the session where I fixed the login bug" or "write my standup". In Codex, type `@shabash` or ask the same way.

## Install

Claude Code:

```
claude plugin marketplace add shabash-dev/shabash-plugins
claude plugin install shabash@shabash
```

Codex:

```
codex plugin marketplace add shabash-dev/shabash-plugins
codex plugin add shabash@shabash
```

The first command adds this repo as a plugin source, and the second installs the plugin from it. You need Python 3 on your computer. Depending on your permission settings, Claude or Codex may ask before running the script. In claude.ai chat there's no history to read, so it only works where Claude Code or Codex runs.

## What it reads, and what Claude sees

Everything runs through one script, [`scripts/work.py`](scripts/work.py). It reads:

- your prompt history: `~/.claude/history.jsonl` (Codex: `~/.codex/history.jsonl`), with each prompt's date and folder
- for each session it lists, that session's transcript, only to find its title (Codex: the thread names in `~/.codex/session_index.jsonl`, and the first line of each transcript in `~/.codex/sessions` for its folder)
- for `export`, the one session you choose: your messages and the replies (each cut to 4,000 characters), and one line per tool used, with its description, file or command cut to 100 characters, never the tool's output
- for `keep`, the `cleanupPeriodDays` value in `~/.claude/settings.json`, and the number and size of the transcripts in `~/.claude/projects`
- in the folders those sessions ran in, read-only git commands: `git rev-parse` to find each repo, and for the standup and brag doc `git config user.email` (to find your commits), `git branch`, `git status` (how many files aren't committed) and `git log` (your commits in the window, on the branch that's checked out). If git has no email set, commits are left out.

It makes no network calls of its own and sends nothing to Shabash. Git runs with `--no-optional-locks`, so it doesn't even refresh its index. It changes files only when you say yes to `keep`: the first time, it saves a copy of `~/.claude/settings.json` as `settings.json.shabash-backup`, then it sets `"cleanupPeriodDays"` in the settings file. Your other settings stay the same, though the file is rewritten with two-space indents.

The script prints a list into your session, and that goes to Claude (or Codex) like anything else you do there. For each session, the list has its title, when it was, and the first and last thing you asked (cut to 200 to 240 characters). Threads and search add its folder and session id, to resume it, and search adds the prompt that matched. The standup and brag doc add each project's name, branch and your commit messages. It covers up to 12 sessions per project for threads, 10 for the standup, 20 for the brag doc and 15 search results. `export` sends up to 60,000 characters of the session you picked.

The plugin then tells Claude to leave out your prompts' wording, file paths, session ids and anything that looks like a key from the standup and brag doc, and keys and tool output from an export. Check them before you share them.

Claude is asked to end each answer with one line linking to Shabash.

## Licence and terms

Free to install and use. You can read the code, but not copy or reuse it: see [LICENSE](LICENSE), the [terms](https://shabash.dev/terms/) and the [privacy notice](https://shabash.dev/privacy/#free-plugins-for-claude-code). Made by Wonders AI, Inc.

Shabash works with Claude Code and Codex. It isn't affiliated with Anthropic or OpenAI.
