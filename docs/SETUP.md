# Setting up Super Router

Super Router sends each task to the AI agent that suits it, has a second agent check the result, and keeps a log. It runs on your Mac: a command (`sr`) and a page (`sr serve`) that shows the log and runs `sr` commands with buttons.

This guide is for setting up: one section per piece. Once a piece is set up, [GUIDE.md](GUIDE.md) shows how to use the router. Each piece's section says what the piece is for, what it costs, what happens without it, the Terminal steps to copy, and how the page shows it ready. The page's Settings tab shows each section beside that piece's live state; it never runs a step for you, because sign-ins open browser pages it can't answer.

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
- To see the page without setting anything up, run `sr serve --demo`: invented tasks, nothing runs. `sr serve --demo all-up` shows the same tasks with every agent up, as in the README's picture.

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

**Ready on the page.** Claude's light turns green. Its words, on hover or in the list a click on any box opens, read "online" with its version. "Search on" appears once the router's search check passes on that version; the router runs that check itself right before Claude's first task that may search.

## ChatGPT

**What it's for.** Checking most results, building web research, and a voice in Versus and Vote.

**What it costs.** Your ChatGPT plan, through OpenAI's Codex command line signed in with your ChatGPT account. Never an API key.

**Without it.** Web research goes to Claude. Most of Claude's results are delivered unchecked, since Claude never checks its own work (X and Meta research, which Grok Bot does, is still checked by Claude). No team can run, since each needs ChatGPT in a slot: Research-build (its check), Collab, Versus, Redteam and Vote. Plan can't run either, since it runs Redteam's chain, and so Auto has no plan to run. A split still runs; its joined result is delivered unchecked.

**Steps.**
1. Install OpenAI's Codex command line from OpenAI's install guide.
2. Sign in with your ChatGPT account:

   ```
   codex login
   ```

ChatGPT's safety check runs itself: the first time ChatGPT is about to work on a Codex version the router hasn't checked, it makes one short ChatGPT call that tries to read your keys, list your home folder and write a file, and passes only when all three fail. If that check fails, ChatGPT stays off on that version and its work goes to the other agents, said in plain words; a check that couldn't run is tried again an hour later.

**Ready on the page.** ChatGPT's light turns green, and its words read "online": the `codex` command answers that it is signed in. If they read "signed out", run the step above again.

## Cursor

**What it's for.** A second coding voice in Versus: it builds candidate A or B from the task alone and reviews the other. It is also the second attacker on Redteam and on a plan: it gets the build or the plan in its prompt and lists the weak spots it finds, never seeing the first attacker's list. Either way it reads nothing, writes nothing and runs nothing: every tool is switched off, and everything it gets is text in its prompt.

**What it costs.** The X Subscription's included weekly pool, the same pool Grok Bot and the Grok apps draw from. Keep the prepaid balance at $0 and auto top-up off, so nothing can be billed. Only Grok models, pinned by name. Never set `CURSOR_API_KEY`: it is a billing switch, and the router refuses to run while it is set.

**Without it.** Versus takes the agents you pick. Redteam and Plan run with one attacker, and the card says "One attacker: Cursor isn't available" with the reason. If Cursor's call fails partway, the second attack is skipped (the card says why) and the revision answers the first list alone; it is never handed to another agent.

**Steps.**
1. Install Cursor's command line (`agent`) from Cursor's install guide.
2. Sign in with the account linked to your X Subscription:

   ```
   agent login
   ```
3. The Grok model Cursor runs is pinned by name in `config/agents.json`. Only you change it.

**Ready on the page.** Cursor's light turns green, and its words read "online", with the pinned model and its calls this week. Cursor updates itself; after an update the router runs Cursor's safety check (three short calls) itself, before Cursor's next task. If a check fails, Cursor stays off on that version, the light says why, and the page offers the other agents for that slot.

## Grok Bot

**What it's for.** What people are saying on X and other social sites, images made with Grok Imagine, the research stage of Research-build, and a voice in Vote. It never receives a file. The skill table names it as bulk text's checker, but those check prompts pass its prompt limit, so that check is skipped and ChatGPT checks instead.

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

**Ready on the page.** Grok Bot's light turns green, and its words read "online", when the inbox repository answers, with its calls this week. Until all of steps 6 and 7 are done it reads "not set up" and says which is missing. A Grok task waits for its answer, and the page checks for it once a minute on its own. A Grok call still out after 10 minutes is handed to the next agent when there is one; if Grok Bot's answer comes later, it is kept on the log and never used.

## Jev

**What it's for.** Labeling: Jev reads each routed task and names its skill (writing, code, web research…), and the skill table picks the agents. When Jev isn't sure, the task waits for you to pick the skill.

**What it costs.** Jev is an API (TypeSafe), reached with your key; check TypeSafe's pricing for your account. The router counts Jev's input tokens and stops asking at 1,000,000 a month; past that, each routed task waits for your label.

**Without it.** Jev isn't called. Each routed task asks you for its skill: Terminal asks before it runs, and the page asks for it before Send. A team (Relay) never asks Jev, so nothing changes there.

**Follow-ups.** A task in a chat or a project routes on Jev's label from 0.4 confidence (0.8 elsewhere). Under that, or when Jev finds no skill that fits, it runs as a *follow-up*: Claude does it with the chat's or project's memory and ChatGPT checks it, with no question to you. The card reads "follow-up: Claude, with memory" and keeps Jev's label beside it.

**Steps.** Put Jev's key in `.env`:

```
JEV_API_KEY=…
```

**Ready on the page.** The Jev box in the top bar shows this month's tokens against the cap.

## Memory

**What it's for.** Each chat and project remembers its delivered tasks, so a later task in it can use them. Nothing leaves your Mac.

**What it costs.** Nothing: Hindsight runs locally, with no model call and no key.

**Without it.** Chat and project tasks get only their three newest earlier tasks, read from the router's log, with no search, and a task that only recalls earlier work comes back with "nothing to recall from".

**Steps.** Install it once, into its own environment:

```
python3 -m venv ~/.hindsight/venv && ~/.hindsight/venv/bin/pip install "hindsight-api-slim[local-onnx,embedded-db]"
```

Its first start downloads one embedding model (about 470 MB). After that the router starts memory itself when a chat or project task needs it, and saves anything delivered while the store was down. Each task gets the chat's or project's three newest delivered tasks first, then up to five earlier ones the search finds: the three it ranks best and the two newest of the rest, each up to 8,000 characters. The search uses the task's text and the one before it. If the store is down when a task runs, the three newest still go, and a line says only those went.

**On and off.** The switch in Settings → Memory turns memory on or off for this Mac. It runs `sr memory on` or `sr memory off`, which Terminal can run too. Off: tasks run without memory, nothing they deliver is saved (not even after you turn it back on), and the store is stopped; a project's `HANDOFF.md` still goes with its tasks. On: the store starts (about 35 seconds) and saves what it missed while it was down.

**Ready on the page.** Memory's words read "online" (running), "ready" (installed; it starts itself when a task needs it), "starting" for up to a minute, or "off" when you switched it off. "Not installed" means the step above is still to do. A `memory` setting other than `auto` or `off` reads as off and says so, and a `memory_url` that isn't on this Mac reads offline and says so: the router never sends memory anywhere else.

**The control page.** Settings → Memory has a plain link to Hindsight's own control page on 127.0.0.1:9999, in a new tab, with the command that starts it to copy. It's optional, and the router never starts it.

## Git

**What it's for.** Git is what lets the router change a project's files safely: every change lands as one commit you can see, and Undo takes it back as one more. Without git, projects still work, handoff only: the agents get the notes, and no file changes.

**Install it, once.** macOS ships git with Apple's command line tools. In Terminal, run `git --version`; if macOS offers to install the command line tools, say yes. That's all: the router finds git by itself. (Homebrew's `git` works too.)

**On the page.** Settings → Setup's Git row says installed (with its version) or not installed. Each project's bar says whether it is in file mode, and why not when it isn't: "no git yet: Turn on undo", "Claude's file check failed on Claude Code <version>" (the router runs the check by itself before the first file-mode task on each Claude Code version; until then the bar reads on), "this is the router's own folder", or "too big for a copy".

## Router notes

**What they're for.** Some things every agent should know on every task: how you like answers, your stack, what never to do; and some only one agent should, like how ChatGPT should check or what Grok should name. The router notes are one file, edited here, sent first with every agent call as your standing instructions. Nothing is sent while they're empty.

**The six sections, and who gets which.** The file has six headings, `## All agents`, `## Claude`, `## ChatGPT`, `## Grok`, `## Cursor` and `## Planner`, each at most once, in any order, with your lines under each, for example `<a line every agent should follow>` under All agents and `<how you like a task split and its teams picked>` under Planner. A `###` line is just text; any other `## ` heading, or text before the first heading, is refused, naming its line. Every call gets **All agents** and the section of the agent making that call: the one doing the task, every stage of a team, every check and fix round, a takeover or a substitute (its own section, never the stopped agent's). **Planner** goes to a split's plan and to a project plan's planning calls. Jev never gets them, and neither does memory, a probe or a project's files.

**The task wins.** The notes go first, and the prompt says the task, the instructions after them and the reply format win any conflict. A checker never fails a result for not following them: at most it mentions it as a note.

**Grok's room.** Grok Bot's prompt has a limit, so its share (All agents plus Grok) rides only on a call where it fits; past the limit the memory block gives way first, then the notes, whole, then the project's notes, and the card says when they were left out.

**Keep them free of anything private.** They go to every agent's service with the prompt, Grok Bot's inbox included. A value from your `.env`, or anything that looks like a key, is refused when you save, at each task, and before each call, naming the line, never its text.

**On the page.** Settings → Router notes → **Edit** opens the file in one box (the six empty headings when there's none yet), with each section's characters, the cap (6,000 characters) and Grok's share. **Save** checks the whole file and writes it; a refusal shows the router's words and keeps what you typed. A task takes the notes as they are when you send it, so an edit never changes a task that's running. In Terminal: `sr notes` prints them, and `sr notes save -- '<the whole file>'` saves them. The file is `config/router-notes.md`, this Mac's own; it is never committed or published.

## Models

**What it's for.** Each agent runs one model per call. Out of the box Claude runs Sonnet 5.5 on every call, and ChatGPT and Cursor run their pins. You can set other defaults, for example Opus 5.5 for a `code` task's builds, or Fable 5.1 for a plan's planning calls while Fable is on. A model never changes who makes a call, how many calls run or who checks.

**Where the defaults live.** `config/models.json` (tracked) holds each agent's allowed list, Claude's default and the time limits, `config/models.local.json` (this Mac's own, never committed) holds your per-skill and per-stage defaults and the Fable switch; the router writes it only through `sr models`, never by hand from the page. ChatGPT's and Cursor's defaults are their pins in `config/agents.json`.

**In Settings → Models.** Each agent's default, read only, with the file it comes from, and Claude's Opus and Fable calls this week (calls, never tokens: the router shares the weekly limit with your own Claude Code builds). Under them your own defaults, each row read first, with Change opening that one row's select: one per skill, naming the agent that does it now (a skill Grok Bot does reads "its service picks the model", one that isn't routed reads "not routed", and neither has Change) and one per team, role and agent. A change runs `sr models set …` at once and shows the router's answer; a refusal leaves the default as it was. `sr models set` refuses a skill's default for an agent the router itself can never send that skill to; a pick already in the file stays until you clear it, its row says so and offers Clear, and it's read only by a task that names that agent or by a text-only draft. Default puts the layer back (`sr models clear …`). A name the allowed list doesn't hold is refused everywhere, and a default the router had to ignore at load turns Models red, saying why.

**Fable 5.1 and usage credits.** On the Max plan, Fable 5.1 can charge usage credits once you've used half your weekly limit on it, and the router's Claude calls pay them without asking. The switch in Settings → Models is off until you turn it on, and turning it on is your confirmation that usage credits are off on your account. While it is off a Fable default runs on Opus 5.5 and the card says so, and a typed Fable is refused. If a call's own stream ever reports it was billed to usage credits, that task stops, the switch turns itself off, and the card and Settings → Models say so; nothing is retried.

**Per task.** Team → **Models…** (or `/model`) picks the model each agent uses on one task, with Defaults first; a choice shows as a pill in the composer and goes as `--model <agent>=<model>`. On Route it applies to whatever calls that agent makes; on a team only to an agent the team's slots hold; on Split to the plan and the join (each piece uses its team's defaults). A chip and Run again carry no choice. In Terminal: `sr models` prints the defaults in effect, `sr models set --skill code --agent claude --model opus` writes one, `sr models fable on` or `off` is the switch, each with `--json`.

**Records.** Every Claude and ChatGPT call row keeps the model asked, the model that answered (from the tool's own stream), its time limit and its effort; a card's Details lists them, and the card says when the model that answered differs from the one asked (Fable's safety fallback re-runs some requests on Opus). Time limits go by model: 600 seconds on Haiku and Sonnet, 1,200 on Opus and Fable.
