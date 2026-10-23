# Setting up Super Router

Super Router sends each task to the AI agent that suits it, has a second agent check the result, and keeps a log. It runs on your Mac: a command (`sr`) and a page (`sr serve`) that shows the log and runs `sr` commands with buttons.

This guide has one section per piece. Each says what the piece is for, what it costs, what happens without it, the Terminal steps to copy, and how the page shows it ready. The page's Setup sheet shows each section beside that piece's live state; it never runs a step for you, because sign-ins open browser pages it can't answer.

**Claude is required. Every other piece is optional.** Without one, the router gives its work to the agents you have and says so on the task: the card names who did the work and why, and a result nobody else could check is marked unchecked. Start with Claude, then add the others in any order.

You never run a maintenance command: the router checks each agent's safety and search itself, and starts memory itself, whenever a task needs them.

## Before you start

- A Mac with Git and Python 3.14 (what the router is tested on). The python3 that ships with macOS is too old for the pinned packages; install 3.14 from python.org or Homebrew.
- Clone the repo, then make its own Python environment and install what it needs:

  ```
  cd ~/super-router
  python3.14 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  cp .env.example .env
  ```

  (Use the folder you cloned into; `~/super-router` is an example.)
- An `sr` command, so you can type `sr route "…"` from anywhere. Add this line to `~/.zshrc`, then open a new Terminal window:

  ```
  sr() { (cd ~/super-router && .venv/bin/python -m router "$@") }
  ```
- Keys live only in `.env`, which Git never commits. No OpenAI key belongs anywhere: the router refuses to run while `OPENAI_API_KEY` or `CODEX_API_KEY` is set.
- To keep a folder out of `sr project add`, list it under `never_register` in `config/settings.local.json`, for example `{"never_register": ["~/Projects/example"]}`: the router then refuses that folder, anything inside it, and a project named like it.
- To see the page without setting anything up, run `sr serve --demo`: invented tasks, nothing runs.

## Claude

**What it's for.** Most building: writing, code, plans, reading images, recalling earlier tasks; it also checks some results and answers in Versus and Vote.

**What it costs.** Your Claude plan, through Claude Code signed in with your Claude account. No API key. When the plan's limit is reached, the router hands that call to the next agent at once (ChatGPT, when it is set up) and the card says so.

**Without it.** Nothing runs: Claude plans and joins splits, does or checks most skills, and is the last agent anything falls back to. Route, Relay and Split refuse every task until Claude is signed in.

**Steps.**
1. Install Claude Code, Anthropic's command line, from Anthropic's install guide.
2. Sign in:

   ```
   claude
   ```

   Sign in with your Claude account when it asks, then quit Claude Code.
3. Check it:

   ```
   claude auth status
   ```

   It should say you're signed in with claude.ai.

**Ready on the page.** Claude's light reads "online" with its version. "Search on" appears once the router's search check passes on that version; the router runs that check itself right before Claude's first task that may search.

## ChatGPT

**What it's for.** Checking most results, building web research, and a voice in Versus and Vote.

**What it costs.** Your ChatGPT plan, through OpenAI's Codex command line signed in with your ChatGPT account. Never an API key.

**Without it.** Web research goes to Claude. Most of Claude's results are delivered unchecked, since Claude never checks its own work (X and Meta research is still checked by Claude, and bulk text by Grok Bot). No team can run, since each needs ChatGPT in a slot: Research-build (its check), Collab, Versus, Redteam and Vote. A split still runs; its joined result is delivered unchecked.

**Steps.**
1. Install OpenAI's Codex command line from OpenAI's install guide.
2. Sign in with your ChatGPT account:

   ```
   codex login
   ```

ChatGPT's safety check runs itself: the first time ChatGPT is about to work on a Codex version the router hasn't checked, it makes one short ChatGPT call that tries to read your keys, list your home folder and write a file, and passes only when all three fail. If that check fails, ChatGPT stays off on that version and its work goes to the other agents, said in plain words; a check that couldn't run is tried again an hour later.

**Ready on the page.** ChatGPT's light reads "online": the `codex` command answers that it is signed in. If it reads "signed out", run the step above again.

## Cursor

**What it's for.** A second coding voice in Versus: it builds candidate A or B from the task alone and reviews the other. It reads nothing, writes nothing and runs nothing: every tool is switched off.

**What it costs.** The X Subscription's included weekly pool, the same pool Grok Bot and the Grok apps draw from. Keep the prepaid balance at $0 and auto top-up off, so nothing can be billed. Only Grok models, pinned by name. Never set `CURSOR_API_KEY`: it is a billing switch, and the router refuses to run while it is set.

**Without it.** Nothing else changes: Cursor only takes a Versus slot you choose for it.

**Steps.**
1. Install Cursor's command line (`agent`) from Cursor's install guide.
2. Sign in with the account linked to your X Subscription:

   ```
   agent login
   ```
3. The Grok model Cursor runs is pinned by name in `config/agents.json`. Only you change it.

**Ready on the page.** Cursor's light reads "online", with the pinned model and its calls this week. Cursor updates itself; after an update the router runs Cursor's safety check (two short calls) itself, before Cursor's next task. If a check fails, Cursor stays off on that version, the light says why, and the page offers the other agents for that slot.

## Grok Bot

**What it's for.** What people are saying on X and other social sites, images made with Grok Imagine, the research stage of Research-build, a voice in Vote, and checking bulk text. It never receives a file.

**What it costs.** The X Subscription's included weekly pool. No API key.

**Without it.** X research and images (Make media) come back to you: web search can't see X posts, and nothing stands in for Grok Imagine. Meta research goes to ChatGPT (or Claude), told it has no live feed and must name where each claim came from; the card says "done without Meta". Research-build researches with ChatGPT. Vote can't run, since it needs three different voters. Bulk text is checked by ChatGPT.

**Steps.** Grok Bot is a Grok routine that the router starts with a webhook and that answers as an issue in a private GitHub repository of yours, the inbox. Below, `owner/inbox` stands for that repository: use your own account and repository name.

1. Make a private repository on GitHub for the answers, for example `owner/inbox`. Leave it empty.
2. Sign the GitHub command line in, so the router can read and close the inbox's issues:

   ```
   gh auth login
   gh auth status
   ```

   `gh auth status` should list `repo` among the token's scopes.
3. On grok.com, make a routine with a webhook trigger. Check on grok.com for where routines and their triggers are made.
4. Give the routine this instruction, word for word, with `owner/inbox` replaced by your repository:

   ```
   A webhook fired with a JSON body. Do the work described in its "task" field. Then, without asking for approval, open a GitHub issue in the private repo owner/inbox whose title is exactly the "task_id" field and whose body is the result. Create it with a GitHub tool that creates the issue directly (on the setup this was written for, the cursor-github create_issue tool). Do NOT use any tool that shows a confirmation or Submit form; if one does, retry with the direct tool so the issue is actually created. If the task produces files (like images) that must be committed, use the authenticated gh CLI on the box to commit them. Afterward, post a brief note in this chat with the result and a link to the issue.
   ```
5. Give the routine GitHub access that can open issues and commit files in the inbox repository. Check on grok.com for how a routine is given GitHub access.
6. Copy the routine's webhook address and key into `.env`, as `.env.example` shows. Check on grok.com for where the routine shows them.

   ```
   GROK_WEBHOOK_URL=…
   GROK_WEBHOOK_KEY=…
   ```
7. Name the inbox repository in `config/settings.local.json` (your own settings file, which Git never commits). It is a setting, not a key:

   ```
   {"grok_inbox_repo": "owner/inbox"}
   ```

   If the file is already there, add the `grok_inbox_repo` line to what it holds.

**Ready on the page.** Grok Bot's light reads "online" when the inbox repository answers, with its calls this week. Until all of steps 6 and 7 are done it reads "not set up" and says which is missing. A Grok task waits for its answer, and the page checks for it once a minute on its own. A Grok call still out after 10 minutes is handed to the next agent when there is one; if Grok Bot's answer comes later, it is kept on the log and never used.

## Jev

**What it's for.** Labeling: Jev reads each routed task and names its skill (writing, code, web research…), and the skill table picks the agents. When Jev isn't sure, the task waits for you to pick the skill.

**What it costs.** Jev is an API (TypeSafe), reached with your key; check TypeSafe's pricing for your account. The router counts Jev's input tokens and stops asking at 1,000,000 a month; past that, each routed task waits for your label.

**Without it.** Jev isn't called. Each routed task asks you for its skill: Terminal asks before it runs, and the page shows a skill menu beside Send. A team (Relay) never asks Jev, so nothing changes there.

**Steps.** Put Jev's key in `.env`:

```
JEV_API_KEY=…
```

**Ready on the page.** The Jev box in the top bar shows this month's tokens against the cap.

## Memory

**What it's for.** Each chat and project remembers its delivered tasks, so a later task in it can use them. Nothing leaves your Mac.

**What it costs.** Nothing: Hindsight runs locally, with no model call and no key.

**Without it.** Chat and project tasks run without what earlier tasks delivered, and a task that only recalls earlier work comes back with "nothing to recall from".

**Steps.** Install it once, into its own environment:

```
python3 -m venv ~/.hindsight/venv && ~/.hindsight/venv/bin/pip install "hindsight-api-slim[local-onnx,embedded-db]"
```

Its first start downloads one embedding model (about 470 MB). After that the router starts memory itself when a chat or project task needs it, and saves anything delivered while the store was down.

**On and off.** The switch on this row turns memory on or off for this Mac. It runs `sr memory on` or `sr memory off`, which Terminal can run too. Off: tasks run without memory, nothing they deliver is saved (not even after you turn it back on), and the store is stopped; a project's `HANDOFF.md` still goes with its tasks. On: the store starts (about 35 seconds) and saves what it missed while it was down.

**Ready on the page.** Memory reads "online" (running), "ready" (installed; it starts itself when a task needs it), "starting" for up to a minute, or "off" when you switched it off. "Not installed" means the step above is still to do.

## Projects

**What it is.** A project is a folder on your Mac with a notes file in it, `HANDOFF.md`. Every task you send in a project carries that file to the agents, and after each task the router adds a short entry about it at the end of the file, inside its own marked block. The agents can't open the folder: `HANDOFF.md`, starting notes included, is all they know about the project. Write there what an agent needs: what it is, the stack, where things are, what's decided.

**New project, on the page.** The `+` on the sidebar's Projects label (or the "New project" line when there are none, or "New project…" at the bottom of the project picker) opens one sheet. Type a name: it is saved as lowercase letters, digits and `-` (`Price Tracker` becomes `price-tracker`). The sheet asks the router what it would do with that name and shows the folder: a new folder, a folder that's already there (it's added as it is, and its `HANDOFF.md` stays yours, so starting notes are off), or the router's reason for refusing. Starting notes are optional; they're written once, at the top of the new `HANDOFF.md`, and notes that look like they hold a key are refused. Create runs the command the sheet shows, then opens the project.

**In Terminal.** The same thing, with the notes in quotes after `--`:

```
sr project new price-tracker -- 'What it is: a price checker for a watchlist.
Decided: no paid APIs.'
sr project new price-tracker --dry-run
```

`--dry-run` says what it would do (make the folder, add the one that's there, or refuse, and why) and writes nothing. For a folder anywhere else, register it as it is:

```
sr project add price-tracker ~/Code/price-tracker
```

`sr project list` shows each project with its folder and the file's line count; `sr project remove <name>` takes it off the list and touches no file. The router never deletes a project's folder or anything in it.

**Where new projects go.** Into `~/Projects`, one folder per project named like it, unless you set `projects_root` in `config/settings.local.json`, for example `{"projects_root": "~/Code"}`. It must be a `~` or absolute path; the router makes the folder itself if it isn't there yet.

**Ready on the page.** The project shows under Projects in the sidebar; pick it, and the composer reads "Project: <name>".
