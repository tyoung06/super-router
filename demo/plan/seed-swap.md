# Plan

The router writes this file from the plan you approved and ticks each step here when it is done. Don't edit it: the router's next write replaces it.

Plan #60 · 2026-10-19 · 0 of 4 steps done

## Steps

- [ ] **Step 1.** Make the skeleton: swap.py that prints a help line, and test_swap.py with one test that runs it.
  - Team: route
  - Done when: test_swap.py's test_help passes under python3 -m unittest
  - Why: the smallest thing that runs, so each later step has a test to stand on
- [ ] **Step 2.** Add offer(packet, grower) that records an offer in swaps.json, with a test.
  - Team: route
  - Done when: test_swap.py's test_offer passes, checking an offer is read back
  - Why: every later step reads the offers
- [ ] **Step 3.** Match offers to wants and print the swaps, with a test that fakes two growers.
  - Team: redteam
  - Done when: test_match.py's test_two_growers passes with faked offers
  - Why: the matching is the part most likely to be wrong, so it gets attacked
- [ ] **Step 4.** Write the README: how to offer a packet and read the matches.
  - Team: route
  - Done when: README.md names both commands and the test command
  - Why: the growers need it

## Needs from you

- Test command: `python3 -m unittest`
