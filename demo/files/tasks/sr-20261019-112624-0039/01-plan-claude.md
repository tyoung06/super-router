## Steps
1. Make the skeleton: board.py printing an empty bean board, and test_board.py with one test that passes.
   team: route
   why: there is no code yet, so step 1 is the smallest thing that runs
   done when: test_board.py's test_empty_board passes under python3 -m unittest
2. Add plant(row, variety) and a test that a second planting in one row is refused.
   team: redteam
   why: the row rule is where a mistake would cost a season
   done when: test_board.py's test_one_planting_per_row passes
3. Research which bean varieties suit a north-facing bed, with sources.
   team: research-build
   why: a research step: it changes no code
   done when: the result names three varieties, each with a source

## Needs from you
- decision: Bush beans or climbing beans first? (step 2)
- test command: python3 -m unittest