# Using Super Router

How to use the router once it's set up. To install it and connect the agents, see [SETUP.md](SETUP.md). Every rule it follows is written down in [RULES.md](RULES.md).

- [The page](#the-page)
- [Teams](#teams)
- [The check](#the-check)
- [When a task stops](#when-a-task-stops)
- [Split](#split)
- [Projects](#projects)
- [Project notes](#project-notes)
- [The spec](#the-spec)
- [Test, Run and Secrets](#test-run-and-secrets)
- [The plan](#the-plan)
- [Auto](#auto)
- [Next steps](#next-steps)

## The page

`sr serve` starts it on your Mac at the address it prints. Its buttons run the same `sr` commands you could type in Terminal. Land, Discard and the other big steps ask first, in words, with the command beside them.

**The top bar.** One box per agent with a light and a name, plus Jev with its count and Memory. It stays pinned as you scroll. Hover over a box for its words; click any box for the full list with the details. A problem shows as the light's colour and an outline.

**Needs you.** Everything waiting on you, at the top of the sidebar: a change ready to land, a plan to approve, a pick, a stopped run. Below it, what's waiting on the router, then your projects and chats, each folding.

**Getting around.** Above 900 px a rail holds New chat, Chats, Projects and Settings, and the sidebar can hide; while it's hidden or the side panel is open, "Needs you · n" moves to the top bar. At 900 px and under, Menu opens the sidebar as a drawer. History, Log files, the report and setup all live in **Settings**.

**A card.** Each task is a card: what you asked, a row of step pills ending in the outcome and the time, then the result. A pill says what a step did: done, running, found issues, failed, stopped, skipped, not started or blocked. **Details** holds who did what, the rounds, what the agents were given and the original answer. **⋯** holds Run again as…, Pin to notes, Save to project and Forget.

**The box.** Type a task and press Enter. **+** holds Attach files, Skill, Web search, Quick task and Project. The team menu (⌥1 to ⌥8) picks Route or a team, with **Models…** at its end, and a team's agents show under the box so you can swap one for this task. `?` lists the shortcuts.

**Try it first.** `sr serve --demo` shows all of this with invented tasks. Nothing runs, and you need no accounts.

## Teams

Route is the default: Jev labels the task, and the skill table picks who does it and who checks it. A team puts several agents on one task instead. Pick one in the team menu, or in Terminal use `sr relay <team> "…"`, `sr split "…"` or `sr plan --project <name> -- '…'`.

| Team | What happens | Default agents |
|---|---|---|
| `research-build` | One agent researches, a second builds from what it found, a third checks | Grok Bot, Claude, ChatGPT |
| `collab` | One plans, the other improves the plan, the first builds, the second edits and checks | Claude, ChatGPT |
| `versus` | Two build their own answers from the task alone and review each other's; you pick the winner | Claude, ChatGPT |
| `redteam` | One builds, two attack it on their own, the builder answers every attack, a checker confirms | Claude, ChatGPT and Cursor, then ChatGPT checks |
| `vote` | Three answer a short question on their own; the majority wins, and a tie comes to you | Claude, ChatGPT, Grok Bot |
| `split` | Claude breaks a task into 2 to 4 pieces, each with its own team; you approve; Claude joins the results | Claude joins, ChatGPT checks |
| `plan` | On a project: turns a goal into up to 12 steps, attacked and checked before you approve them | Claude plans, ChatGPT and Cursor attack, ChatGPT checks |

**Swap an agent for one task.** A team's slots show under the box, each a menu of the agents it allows. In Terminal: `sr relay versus "…" --b cursor`. No agent ever checks or attacks its own work, so a swap that would break that is refused.

**When a team's agent is missing.** The router fills the slot with another agent when the rules still hold, and the card says so. If no agent can take it, the team refuses before anything runs and names the slot. [SETUP.md](SETUP.md) says what each missing piece costs you.

## The check

**Must and note.** The checker lists every problem it finds once, each marked `[must]` (it makes the result wrong or incomplete for the task: a wrong fact, code that doesn't work, a part not done, a limit broken) or `[note]` (wording, tone, a claim it couldn't check). Only a must fails a result. A pass can carry notes: the card reads "Passed · ChatGPT · 2 notes", folded under the verdict. One fix round fixes the musts; the re-check says, for each must, fixed or not fixed, and fails only for a must still open or a new problem the fix made. A failed check lists the musts it left open.

**Blocked.** When the result says it couldn't do the task because something it needed wasn't given (your notes, a file, a decision), and no search could find it, the check answers Blocked instead of asking for a fix the doer can't make. The task ends with no fix round; the card reads "Blocked: <what it needed>", and Run again puts the task's text in the box so you can add what's missing.

**Land anyway.** A change whose check didn't pass can still land, on purpose: its card offers **Land anyway** beside Discard (and Needs you lists it), and the confirm says the check didn't pass and lists the open musts. The commit and the `HANDOFF.md` entry both say "check not passed"; Undo works as for any land. In Terminal: `sr land 5 --anyway`.

**What was sent.** Every check, re-check and fix prompt is kept beside its output in the task's folder (`tasks/<task>/`, a file ending `-prompt.md`), so you can read exactly what the checker was given.

## When a task stops

**Most stops take care of themselves.** A call that fails, hits a plan limit or gets no answer in time goes to the next agent at once, once per task, and the card says who took over and why. Never handed over: image making, X research, `@agent` tasks, `versus`, `vote` and Cursor's calls.

**What stays with you.**
- **Resume** (`sr resume 5`): continues a task whose process ended, with the same agent, or a plan-limit stop the takeover couldn't take, with the other of Claude and ChatGPT. Once per task.
- **Fallback** (`sr fallback 5`): after a task fails its check twice, its checker redoes it once and the original doer checks. A task that changes project files never falls back: discard it and run it again.
- **Land anyway** and **Discard**: for a kept change whose check didn't pass (see [The check](#the-check)).
- **Cancel** (`sr cancel 5`): stops a running task. A stopped page leaves its tasks running.

Nothing is ever bought to keep going: at a plan's limit, another agent takes over or the task stops.

## Split

**What it is.** Split is for a task that is really several separate things. Claude plans it as 2 to 4 pieces and gives each a team, picked from the teams that can run now, with one line on why. You approve the plan; the pieces run one at a time, each as its team; Claude joins the results and ChatGPT checks the whole (without ChatGPT the joined result is delivered unchecked, and the plan says so first). When the parts can't run apart, because each needs the one before it, Claude says so in one line and nothing runs: the grey No split card's **Route it** sends the same text as a routed task.

**A team per piece.** A piece goes to `route` (Jev labels it and the skill table picks who does it and who checks it) or to one of the teams: `research-build`, `collab`, `versus`, `redteam` or `vote` (on a project, never `versus`). A versus piece waits for your pick, and a vote piece for your pick on a tie; meanwhile the next piece runs (on a project the next one waits, since they share one copy), and the join waits until every piece is in. The plan's card shows, for each piece, where it goes and who does it, and at the end about how many agent calls the split makes from here, and how many with fix rounds. Nothing runs until you approve.

**Editing the plan.** On the plan's card, **Edit** opens a piece's text in place: under 400 characters; Esc cancels, ⌘↵ saves. A new text is labeled again (one Jev label). A piece's team select changes its team at once, and the card shows "you changed it from" the planner's team. **Approve** and **Reject** each ask once more. In Terminal:

```
sr split --edit 7 --piece 2 --team versus
sr split --edit 7 --piece 2 -- 'Write the FAQ as five questions.'
sr split --go 7
```

**An agent per piece.** A piece on a team other than route shows its slots on the plan's card, each a menu of the agents that slot allows (the default marked); a change runs at once, for example Cursor building versus's B. A team change clears them. In Terminal: `sr split --edit 7 --piece 2 --slot b=cursor` (`--slot b=default` puts the default back).

**Splitting on a project.** Pick a project in the composer before you send a split (in Terminal, `sr split --project price-tracker -- '…'`). On a project with git, all the pieces build in one copy the split owns, one after another in plan order, and each piece's own part of the change shows under it. Claude then joins them in the copy, the project's tests run, and ChatGPT checks the whole change. A piece never lands on its own. When a piece stops or fails its check twice, the pieces after it wait: resume it, **Skip** it (the copy goes back to where that piece started), or cancel the split. Without git, a split on a project is handoff only: each piece gets the notes, and the split adds one entry to `HANDOFF.md`.

**Landing once.** When the joined change passes its check, the split waits to land like any project task: **Land** makes one commit of the whole change and the split's one `HANDOFF.md` entry, **Undo** is one more commit, **Discard** drops the copy. Before the join, Reject or cancel the split to drop the copy. In Terminal: `sr land 7`, `sr undo 7`, `sr discard 7`.

## Projects

**What it is.** A project is a folder on your Mac with a notes file in it, `HANDOFF.md`. Every task you send in a project carries that file to the agents, and after each task the router adds a short entry about it at the end of the file, inside its own marked block. Write there what an agent needs: what it is, the stack, where things are, what's decided. With git (below), Claude can also change the project's files, on a copy, and you land each change.

**New project, on the page.** The `+` on the sidebar's Projects label (or the "New project" line when there are none, or "New project…" at the bottom of the project picker) opens one sheet. Type a name: it is saved as lowercase letters, digits and `-` (`Price Tracker` becomes `price-tracker`). The sheet asks the router what it would do with that name and shows the folder: a new folder, a folder that's already there (it's added as it is, and its `HANDOFF.md` stays yours, so starting notes are off), or the router's reason for refusing. Starting notes are optional; they're written once, at the top of the new `HANDOFF.md`, and notes that look like they hold a key are refused. Create makes it, then opens the project.

**From an idea.** The switch at the top of that sheet, **Blank | From an idea**, turns the notes box into **Your idea**: required, at most 2,000 characters, with a counter. **Create and draft the spec** makes the project with your idea as its notes and fills the box with Draft it. Nothing is sent until you press Send.

**In Terminal.** The same thing, with the notes in quotes after `--`:

```
sr project new price-tracker -- 'What it is: a price checker for a watchlist.
Decided: no paid APIs.'
sr project new price-tracker --dry-run
```

`--dry-run` says what it would do (make the folder, add the one that's there, or refuse, and why, and whether git is set up) and writes nothing. A new project gets git at once: a `.gitignore` and one first commit of `.gitignore` and `HANDOFF.md`. To use a folder from somewhere else, move it into `~/Projects` (or your `projects_root`) in Finder, then type its name in the New project sheet: it's added as it is. In Terminal, a folder can also stay where it is:

```
sr project add price-tracker ~/Code/price-tracker
```

`sr project list` shows each project with its folder and the file's line count; `sr project remove <name>` takes it off the list and touches no file. The router never deletes a project's folder or anything in it.

**Where new projects go.** Into `~/Projects`, one folder per project named like it, unless you set `projects_root` in `config/settings.local.json`, for example `{"projects_root": "~/Code"}`. It must be a `~` or absolute path; the router makes the folder itself if it isn't there yet.

**Ready on the page.** The project shows under Projects in the sidebar. Pick it to open its view: what you send from there goes to that project.

**Files: what changes and who changes it.** On a project whose folder has git (a repository with at least one commit, on a branch), a task you send with the project runs in *file mode*. At the start the router copies the files git tracks into a scratch folder of its own, outside the project (in `~/Library/Application Support/super-router/`). Only Claude's build calls work there, with file tools that read and write inside that copy and no tool that runs a command. The copy never holds `.git`, `.env` or any `.env.*`, `.claude/`, `.mcp.json`, `.cursor/`, `.codex/`, `HANDOFF.md` (it rides in the prompt) or a link. ChatGPT, Grok and Cursor never see the folder or the copy: a checker gets the change as a diff, with the tests' results. A task whose agent isn't Claude runs as before, and its card says it can't change project files. The folder itself is never touched until you land.

**Tests.** On the project's bar, "Tests: none · Set" opens a one-field sheet: type the command you'd run, for example `python3 -m unittest`, and Save. After each change Claude makes, the router runs it on a throwaway copy of the copy, in a macOS sandbox: no network, no keys, no reading anything else in your home folder, writes only in the throwaway, five minutes at most. A command starting `.venv/` uses the project's own environment, read only. The checker sees the results, and a failing test fails the check unless the result explains it. In Terminal: `sr project tests price-tracker -- 'python3 -m unittest'`, and `--clear` to remove it.

**Land, Undo, Discard.** A task that changed files and passed its check waits for you: its card lists the files (each opens its diff in the side panel) and offers **Land** and **Discard**, and Needs you says "Ready to land". Each asks once more, naming the command. Land puts the change into the folder as one commit on the task's branch, holding the changed files and `HANDOFF.md` and nothing else; your own edits elsewhere stay as they are. If one of the change's files has edits of yours, or the branch changed it since, Land refuses and writes nothing. After a land the card reads "Landed · <id> · Undo": Undo is one more commit putting those files back. Discard drops the change: the copy goes and the folder stays as it is. Nothing ever rewrites git history. In Terminal: `sr land 5`, `sr undo 5`, `sr discard 5`.

**Every team on a project.** Any team takes a project. `research-build` and `redteam` build in the copy as a routed task does; on `redteam` Cursor may still attack, with the change as a diff and the tests' results in its prompt, never the folder or the copy. `collab` plans in the copy (reading only), the partner improves the plan, the lead builds in the copy, and the partner checks the change with the usual check. `vote` gives each voter the project's notes and changes no file; its entry is one line with the answer.

**Versus on a project.** With git, versus makes two copies, one per candidate. Claude builds in its own copy; ChatGPT reads the project's files from its prompt and gives each changed file whole in its reply, and the router writes them into its copy (ChatGPT never touches a folder). Each copy runs the tests, and each reviewer sees the other's change. The card shows each candidate's files and tests beside its text. When you pick one, its copy waits to land (Land, Undo, Discard as above) and the other copy goes; Neither drops both. Versus on a project takes Claude and ChatGPT only.

**Turn on undo.** A project without git shows "Turn on undo" on its bar. It shows first what git would track (with your `.env` left out), then, on Confirm, adds `.env`, `.env.*`, `.venv/`, `venv/`, `__pycache__/`, `node_modules/` and `.DS_Store` to `.gitignore` where missing, runs `git init`, and makes one first commit. A file that looks like it holds a key stops it, naming the file and line. In Terminal: `sr project git price-tracker` (and `--dry-run`).

**Adding files.** Drop files on the project's bar (or use "Add files…"): a sheet lists them, and Add copies them to the project's top level as one commit, with a line in `HANDOFF.md`. Any kind of file goes in: code, data, images. A file whose name is already in the folder is refused, never overwritten; so is a file over 50 MB, a name starting with a dot (like `.env`), or a text file that looks like it holds a key, each named in the sheet. In Terminal: `sr project files price-tracker --file data.csv`.

## Project notes

**What rides on every project call.** A project's notes are the part of its `HANDOFF.md` above the router's block: what it is, the stack, what's decided, and anything its tasks should believe. The whole file goes with every call of every task in the project, so the notes are the place to correct what the project's tasks think: change a line here and the next task reads the new one.

**Editing them on the page.** On the project's bar, **Notes** opens them in a box, with the router's block shown read-only under it, their lines and characters and the cap (20,000 characters). **Save** writes the part above the block and leaves the block exactly as it was; with git (and `HANDOFF.md` tracked) it's one commit holding `HANDOFF.md` alone, `sr: notes edited`; without git the file is written and nothing is committed. A line that is one of the router's markers, a value from your `.env`, or anything that looks like a key is refused, naming the line, never its text. If the notes changed since you opened them, Save says so and writes nothing; open them again. Closing with unsaved text asks once. In Terminal: `sr project notes <name>` prints them, and `sr project notes <name> --save -- '<the notes>'` replaces them.

**Pin to notes.** On any finished card with a result, **Pin to notes** (in the card's ⋯ menu) keeps a piece of it in a project's notes: select the part you want inside the result first (or nothing, for the whole result), and the sheet opens with that text, which you can edit, and the project (the task's own, or pick one). Save adds it at the end of the notes under `### Pinned from #<n> (<date>)`, as one commit. In Terminal: `sr project pin <name> --task <id> -- '<text>'`.

**Save to project.** On a done card, **Save to project** (in the ⋯ menu) writes the result into the project as a new file: the sheet proposes `docs/<a name from the result>.md`, which you can change (a `.md` or `.txt` file inside the project's folder; no part starting with a dot; never `HANDOFF.md`). Save makes one commit holding the file and a line in `HANDOFF.md`. A file already there is never overwritten; a result that looks like it holds a key is refused; a project needs git first (Turn on undo). In Terminal: `sr project save <name> --task <id> --path docs/<name>.md`.

**Forget and Remember again.** A finished card of a chat or project task offers **Forget** in its ⋯ menu: the task leaves memory, so no later memory block carries it and no search finds it; the log keeps it, and its card reads "Forgotten" with **Remember again**, which puts it back. Forget never touches `HANDOFF.md`: to correct a project's notes, edit them. In Terminal: `sr forget <n>` and `sr forget <n> --undo`.

## The spec

**What it is.** A project can carry a spec: `SPEC.md` at its top level, yours, saying what the project is for. It rides on every agent call of every task in the project, as data, after the task and before the handoff notes, and the checkers are told that a result which contradicts an item of it, where the task didn't ask to, is a must. Two lists in it are read by code when they are there: `## Examples` and `## Done when`, each a `-` or numbered list, one line per item; the router labels them `E1, E2, …` and `D1, D2, …` by order (the file's own numbering never counts). A spec with neither list rides as text, and nothing below that needs a label applies. It is read once when a task starts and kept with the task, so an edit never changes a running task; a step of an Auto run reads it when that step starts. It is capped at 6,000 characters (`spec_max`), and a line holding a value from your `.env`, or anything that looks like a key, refuses the task, naming the line.

**Only you change it.** No agent writes `SPEC.md`: a build that changes it in the copy has it put back before the check (the card says so), and Land refuses a change that still touches it. Your own ways in: the Spec section below, **Save to project** at `SPEC.md` on a done card (refused when the file exists; the section replaces), and files in.

**From a draft.** A delivered Draft it card has **Save as SPEC.md** as its main action while the project has no spec: one commit holding `SPEC.md` and the draft's entry. Read it after saving: the draft's whole text is saved, so a `## Missing` section may say the file still needs saving; edit that out in the Spec section. Once it's saved, the card's first chip is **Plan the project**. On that card, every item of **Run again as…** fills the box and sends nothing, and Route stays text only.

**Editing it on the page.** The project's **Notes** sheet has a **Spec** section below the notes: the file in a box, the lines and characters and the cap, and, under it, the items as the router read them (`E1 c_to_f(100) == 212`, `D1 both functions pass their tests`), so you see what the agents will be held to. **Save** writes the file whole: with git it is one commit holding `SPEC.md` alone, `sr: spec added` for a first one and `sr: spec edited` after; without git the file is written and nothing is committed. Over the cap, a `.env` value or a key shape is refused naming the line, never its text, and the box keeps what you typed; a file that changed since you opened it is refused too (open it again). A save is allowed while a task of the project is open, a plan waiting for your approval or an Auto run included; Approve and Land still work after it, since the spec is never part of a change. A project without one reads "Spec · none" with **Draft it**: it fills the box with a text-only task ("Write SPEC.md for this project: …", `--no-files`, so the put-back can't undo it); read the result, then Save to project at `SPEC.md`. In Terminal: `sr project spec <name>` prints it with its hash and labels; `sr project spec <name> --save -- '<the spec>'` replaces it; `sr route --project <name> --no-files -- '<text>'` runs a project task handoff only.

**Covers.** With an Examples list, each plan step says which examples it covers (`covers: E1, E3`, or `none`). The plan's card and `docs/PLAN.md` show it ("Covers E1–E3; not E4"); an example no step covers is a note, never a must.

**When it changes.** A running task keeps the spec it started with. Once the file differs from the one a plan was made from, What now? offers **Revise plan**, a waiting plan says so before you Approve, and Auto stops before its next step; turning it on again takes the new spec.

## Test, Run and Secrets

Three buttons on a project's bar. None of them calls an agent or a model.

**Test.** Runs the project's test command (Set it first, beside "Tests") right now, exactly as the router runs it after a build. It runs on a throwaway copy of the files committed at the project's head, inside the macOS sandbox:
- no network and no keys;
- nothing else in your home folder read;
- five minutes at most.

The copy is removed when it ends, and the project's folder is never touched. Test doesn't ask first: it changes nothing. Its output opens in the side panel and follows the run. The bar then shows the last result and when ("Tests passed · 10:42"). Test is off, with the reason, when the project has no test command, no git or commit, or is the router's own folder. In Terminal: `sr project test price-tracker` (and `--status` for the output so far).

**Run.** Starts the project's own program in its real folder, as you would in Terminal. Set its run command once, beside Run, for example `python3 app.py`. Run asks first: its question names the command, the folder, and the names in the project's `.env` it will pass, never a value.
- **It gets** your normal environment with the router's own keys and the per-token billing switches taken out, and the project's `.env` on top.
- **It isn't sandboxed** and has no time limit.
- **Only your click starts it.** Nothing in the router, no agent and no task ever starts one, and a run that ended is never restarted.
- **Closing the page or Terminal doesn't stop it.** The bar reads "Running since 10:42", and **Stop** ends it (it asks first): SIGTERM, then SIGKILL after 10 seconds. The bar then reads "Exited 0 at 10:45" or "Stopped at 10:45".
- **Its output shows in the side panel**, with any key from the router's `.env` or the project's replaced by `[REDACTED]` before it is written.

In Terminal: `sr project run-command price-tracker -- 'python3 app.py'`, `sr project run price-tracker`, `sr project run price-tracker --status` and `sr project stop price-tracker`.

Run refuses when:
- the project's `.env` is a link;
- the project has git and its `.env` is tracked or not ignored;
- the project is the router's own folder;
- a run is already going.

**A list of programs Run never starts.** `never_run_env` in this Mac's `config/settings.local.json` (never in a tracked file) is a list of name parts, for example `{"never_run_env": ["FAKEBROKER"]}`. Run refuses any project whose `.env` holds a name containing one, saying which part matched. A clone has none, so every program runs.

**Secrets.** Lists the names in the project's `.env`, each set or empty, and never shows a value.
- **Add** takes a name (capital letters, digits and `_`, like `WEATHER_API_KEY`) and a value typed into a password field.
- **Change** replaces a value; **Remove** asks once.
- The value goes to `.env` and nowhere else: never on a command line, in the log, in a JSON or in the page's Run log. The router gets it on its standard input, writes the file whole (every other line as it was, the file readable only by you), and the page clears the field at once.

Secrets refuses:
- a `.env` that is a link;
- with git, a `.env` that git tracks or doesn't ignore (Turn on undo, or a `.env` line in `.gitignore`, fixes that);
- the router's own folder, whose `.env` stays a Terminal step;
- a value with a second line, or one `.env` readers would change (it holds `${...}`).

In Terminal: `sr project secrets price-tracker`, `sr project secrets price-tracker --set WEATHER_API_KEY` (it asks for the value without showing it, or reads it from a pipe) and `--remove WEATHER_API_KEY`.

## The plan

**What it is.** Plan is a team for a project: it turns a goal into a short list of steps you can trust before any of them runs. Pick a project, pick **Plan** in the team list (⌥8, or type `/plan`), and say what to plan: a goal, a focus, or "Plan the first version." Claude plans from the project's own files (it reads a copy of them and changes nothing), ChatGPT and Cursor each attack the plan on their own, Claude revises it against both lists, and ChatGPT checks it: about 5 to 7 agent calls, 4 to 6 when Cursor isn't available. Plan needs the project's files, so a folder without git says "Turn on undo first"; on a project whose plan still has an open step, Plan makes a revision of it (below). In Terminal: `sr plan --project demo -- 'Plan the first version.'`.

**What a plan holds.** Up to 12 steps, each a task the router can run as it stands, with its team (Route or a team on the plan's menu: research-build, collab or redteam), a one-line why, and its finish line, written as something a check can confirm: a step that changes code is done when a named test passes, so the tests the router runs after its build show it. On a project with no test command, or whose last Test didn't pass, step 1 is the smallest skeleton that runs with one passing test. **Needs from you** comes first, before anything runs: each key a step needs (by its name in the project's `.env`), each account, each decision left to you, and a test command when the project has none.

**One step.** When the text is really one step's work, Claude says so in one line and nothing is planned or attacked: the grey One step card's **Build it** fills the box with that step's task, its team and the project.

**Questions first.** On a new plan, never a revision, Claude may ask up to 3 questions when an answer would change the steps. The plan's card shows each with its options as chips, the planner's guess marked but not picked, and **Other…** last in the row, which opens a box for your own words (Esc or clearing it leaves the question unanswered). **Send answers** turns on once each has an answer; **Use your best guess** takes the planner's guesses. The plan holds the project until you answer or cancel it. Your answers ride on every later call of the plan; at Approve they land in `docs/PLAN.md` under "Decided before planning" and fill the notes' one section, "Current plan's decisions", which each new plan replaces, even if you edited it, and its Undo puts back. In Terminal: `sr plan --answer <task> --pick 1=A --other 2='<your words>'`, or `--best-guess`.

**Approving it.** The plan waits as a card: each step with its team, why, finish line and its team's calls, the needs (each key marked set or not set, with a **Secrets** button naming it; the proposed test command with **Set**), the total calls for all the steps (Jev's labels counted apart), then the check's verdict and both attack lists, folded. Before you approve, **Edit** changes a step's text or its finish line, its team select changes its team, ↑ and ↓ move it, and **Drop** takes it out; each change is checked by the same rules, renumbers the needs, and shows in `docs/PLAN.md` at once. **Approve** lands `docs/PLAN.md` and the router's `HANDOFF.md` entry as one commit; **Reject** drops it; after a failed check, **Approve anyway** lands it with the check's open musts named first. A landed plan never changes except by its ticks. In Terminal: `sr plan --edit 12 --step 2 --team redteam`, `sr plan --edit 12 --step 3 --up`, `sr plan --edit 12 --step 2 --text -- 'New words'`, then `sr land 12` (or `sr discard 12`).

**Steps and ticks.** With a plan landed, What now? offers **Build step 1: …**: it fills the box with the step's text, its team and the project, plus a Step pill ("Step 1 of plan #12"). You may change the words or the team; the task is still that step, held to its finish line (its check fails it when the named test isn't there, doesn't test what the step says, or isn't passing). Steps run one at a time, in order. When a step's change lands, the same commit ticks it in `docs/PLAN.md`, naming the task that did it; a step that changes no file (research, say) is ticked in its own commit; an Undo opens it again. A step that fails, stops or is discarded stays open. `docs/PLAN.md` is the router's: a change an agent makes to it is put back, uncommitted edits of yours are left out of the commit (the card says so; the tick still counts), and a change committed outside the router is written over (git keeps it). The project's bar shows **Plan #12 · 1 of 4**, which opens `docs/PLAN.md`, read only. In Terminal: `sr route --project demo --step 12:1 -- '…'` (or `sr relay <team> … --step 12:1`).

**Revise plan.** While the current plan has open steps, Plan revises it instead of refusing: **Plan again** in the plan's panel (from "Plan #n · d of m", beside the Stop here toggles) fills the box with Plan and the project, and you say what should change; **Add to plan** on an idea's row in the Ideas sheet does the same with the idea's text and the Idea pill. The done steps stay exactly as they are and keep their ticks; the planner returns only the steps after them, numbered on from the last done one, and says under `## Changed` which open steps it changed or dropped and why. Every agent on the revision sees the current plan as `docs/PLAN.md` renders it, with its ticks. The revision's card shows the done steps first, greyed, each with its task; the new steps are editable as any waiting plan's; "revises #n" is in its head. Approve lands `docs/PLAN.md` titled "Plan #m (revises #n)"; the old plan is no longer current (its Undo is refused), and the revision's own Undo makes it current again. A step whose failed change is still kept must land anyway or be discarded first, and a project with a task open (an Auto run among them) is refused as always. In Terminal: `sr plan --project demo -- 'Add a Kelvin column after step 2.'`, or `sr plan --project demo --idea 3 -- '<the idea's text>'`.

**Needs, and the finish line.** Before a step whose key isn't set, What now? reads "Before step 2: set WEATHER_KEY" with Secrets, or "Before step 1: set the test command" with **Set** (it asks once, naming the words); nothing stops you sending the step anyway. When every step is done, What now? reads "All 4 steps done" with **Write the README**, **Set the run command** (when none is set) and **What next** (a new plan), until you send something else. With a `## Done when` list in the spec, **Check against the spec** comes first and Set the run command stays in Project tools. A delivered result on a project with no plan offers **Plan from #<n>** among its chips.

## Auto

**What it is.** Auto runs a project's plan for you, step after step, in one copy of the project, and stops where you would want to look. It is a switch at the right end of the project's What now? line, and `sr auto <project> --on` in Terminal. Nothing else starts a run: no schedule, nothing after a restart.

**The switch.** It shows **Off** when a run could start now (a landed plan with an open step, file mode on, Claude available, no other task open on the project, the next step's key and the test command set), **On** while a run runs, and not at all otherwise (What now? says what is in the way). Turning it on asks once, with the router's own numbers: the steps the run covers, the budget, the first stop-here, and that a step already started finishes, so a run can pass its budget by up to one step's calls. Turning it off stops the run after the step in progress, never mid-call; it is the only Stop.

**What a run does.** The router makes one copy of the project and runs each step as its team would, exactly as Build step k sends it (the same prompts, the same models), one at a time, in the copy; after each build the project's tests run. A step that passes goes into the run and is ticked in the copy's `docs/PLAN.md`; nothing is committed in the folder while the run goes. A step that fails its check twice is tried once more from the copy as it stood when the step started. The run's steps show as cards of their own (step k of run #n) with no Land on them.

**Where it stops.** Before a step you marked **Stop here** (in the plan's panel, from "Plan #n · d of m": a toggle per step, kept in the log, nothing committed); at the budget (`ceil(1.5 × U)`, U the plan card's upper estimate for the steps left; the calls of every step's agents count, retries and takeovers included); when a step fails again after its retry, is blocked, or is delivered unchecked; when a step stops (a plan limit nobody could take over, a process that ended); when the spec changed since the run started; when a call is billed to usage credits; before a step whose key or test command isn't set; when Claude isn't available; on a cancel, or the switch turned off. Each stop waits in Needs you as "Auto stopped: <why>", with the run's copy kept. Turning Auto on again goes on from there, in the same copy: the stopped step is resumed where Resume allows, or started again; a mark at that step is passed for the run; after a budget stop the budget becomes the calls used plus `ceil(1.5 × U_left)`. It is refused, with why, while the cause is still there.

**The recap, and landing.** The run's card is its recap: each step with its state, its task, its calls and its checker's verdict (and its mark), the calls used against the budget, what is still open, and why it stopped. At the plan's end the run waits to land: **Land run** puts the whole change in the folder as one commit (the run's paths, `docs/PLAN.md` with every passed step ticked, and `HANDOFF.md` with one entry built from the steps' sections), **Discard run** drops the copy, and Undo takes the whole run back. A stopped run can be landed as it stands with **Land the run so far**: what lands is the copy as it was when the stopped step started, so only the steps it passed land. Each step's memory is stored when the run lands, none on Discard. In Terminal: `sr auto <project> --on`, `--off`, `--status`, `--on --dry-run` (what a run would cover, nothing written), `sr plan --stop-here <plan task>:<k> on|off`, then `sr land`, `sr discard` or `sr undo` on the run.

## Next steps

**Chips.** When a task is delivered, the newest card of a chat or a project offers its next moves as chips under the result, labeled "Next": at most three, real buttons. The router's own come first: **Build step k** while the project's plan has an open step, otherwise **Plan from #<n>** (on a project) and **Build from #<n>**. Then come the agent's suggestions, which it writes in an optional `## Next` section at the end of its reply (on a project they come from the `### Next` lines of its handoff instead). A chip never sends anything: it fills the box with team Route, the view's chat or project and the line, for you to read, edit and send. If you had typed something, it's replaced, and **Undo** in the toast puts it back for 10 seconds; Esc clears the box and its pills. An older card keeps its chips in Details, under "Suggested next". `## Next` is a note, never part of the result: no checker judges it, it never goes to another call, into memory or into a saved file, and `sr show <n>` prints its lines under `Next:`.

**Build from this.** **Build from #<n>** fills an empty box with a From pill: the task you send carries that earlier result whole, as data, to every call (the doer, each stage, the check, the fix round, a takeover, a resume and a fallback), in a block labeled `EARLIER RESULT · #<n>` after the task and before the project's handoff and the memory block. It is the result as `sr show` prints it, without its `## Handoff` and `## Next` sections, cut at 20,000 characters (`from_max`) with a line saying so. The checker gets it too, with a line saying you chose it, and still checks what the new result takes from it. The new card reads "Built from #<n>", and Details' What the agents were given shows the block. The source has to be delivered with a text result and not forgotten; Grok never gets the block cut to fit its limit, so a team whose Grok stage it would push past the limit is refused, and a routed task Grok would do comes back after its label. In Terminal: `sr route --from 12 'Write the script from the first API.'` (or `sr relay <team> --from 12 '…'`; never on a split).

**What now?** A project's pinned head has one line under its title with the one move that fits now, chosen by the router in this order: an Auto run's own line while it has one; a task waiting on you ("Waiting on you: #7 · a change ready to land", with Open), a task running ("#7 is running · Claude on stage 2 of 4 (build)"), the newest task that ended without delivery ("#7 failed its check", with Open), the spec changed since the plan (with **Revise plan**), the plan's next need, Build step or finish line, its next move when it was delivered ("Next: Add a --round option", with that chip), or "Send a task to start." on a project with no tasks yet. It stays in view when a narrow window folds the project's bar into Project tools. In Terminal it's `what_now` in `sr log --json --project <name>` and in `sr project list --json`.

**The Ideas list.** Each project keeps a list of one-line things you may want to do later, in the router's log (never in the project or in memory). On a project card, an agent chip's small × (**Later**) moves its line there, and it isn't offered on that card again; the project's bar shows **Ideas · <k>**, which opens the list: each idea with where it came from ("Later on #12", linked, or "Added") and its date, **Send** (which fills the box like a chip, with an Idea pill) and **Dismiss** (which asks once; the log keeps it), and a box to **Add** one. While the task sent from an idea is open it reads "sent as #<n>"; once delivered (a change, once it lands) the idea moves to the list's folded **Used (n)** ("used by #n"), and if the task ends any other way the idea is open again. A text is one line of at most 400 characters, never starting with `@` or `/`, and never a key; a project keeps at most 50 open ideas (`ideas_max`). In Terminal: `sr ideas demo`, `sr ideas demo --add -- 'Add a Kelvin column.'`, `sr ideas demo --dismiss 3`, and `sr route --project demo --idea 3 -- '…'`.

**Suggest ideas.** A button in that list: one Claude call reads the project and adds up to 3 ideas, read "Suggested by #n". It is never checked, since you judge each idea and Dismiss works as usual, and it doesn't hold the project. One runs at a time, and it's off from 48 open ideas. It has no card in the stream; it shows in History and `sr log`. In Terminal: `sr ideas demo --suggest`.
