Notes from the person who sent this task, kept for every task they send. They are part of this message: follow them where they fit this task. The task, the instructions after these notes and the reply format win any conflict.
--- notes ---
<a line every agent follows, such as how you like answers>

<a line for Claude alone>
--- end of notes ---

How the person likes a task split and its teams picked. The menu and its rules win any conflict: never a team the menu doesn't offer.
--- planner notes ---
<how you like a task split and its teams picked>
--- end of planner notes ---

Two things: a welcome sign for the tool shed, and when the seed library should open.

Break this task into 2 to 4 pieces that can each be done on their own, by one team, without any other piece's result. Each piece is a complete task in one or two sentences, with everything it needs stated in it. No two pieces may ask for the same search or the same work. Work that needs another part's result stays in one piece with that part: a function and its tests are one piece. Give each piece the one team from the TEAMS list below whose way of working fits it best. When the task names a team for a part, give that part that team if the list has it; if the list doesn't, give it the closest team on the list and say so in its why. Then say in one line how the finished pieces join into one result. Return exactly: `## Pieces` (a numbered list; under each piece, a line `team: <a team's name from the list>` and a line `why: <one line on why that team fits it>`), `## Join` (one line). Do not do any piece. If the task is one chain, where each part needs the one before it, do not split it: return only `## No split` with one line saying why.

TEAMS a piece may take (the router built this list from what can run now; "you" in a line is the person who asked):
- route: Jev labels the task; the skill table picks who does it and who checks it. Chain: Jev's label → the skill table's doer → its checker. About 2 calls.
- research-build: One agent researches the web and X, a second builds from what it found, and a third checks the result. Chain: Grok research → Claude build → ChatGPT check. About 3 calls.
- collab: Two agents work as a pair: one plans, the other improves the plan, the first does the work, and the second edits and checks it. Chain: Claude plan → ChatGPT amend → Claude build → ChatGPT edit (check). About 4 calls.
- versus: Two agents each build their own answer from the task alone and review each other's, then you pick the winner. Chain: Claude build → ChatGPT build → ChatGPT review → Claude review → your pick. About 4 calls.
- redteam: One agent builds, two others attack it on their own, the builder fixes what they found, and a checker confirms the fixes. Chain: Claude build → ChatGPT attack → Cursor attack → Claude revise → ChatGPT check. About 5 calls.
- vote: Three agents answer the same short question on their own; the majority wins, and a tie comes to you. Chain: Claude vote → ChatGPT vote → Grok vote → tally. About 3 calls.