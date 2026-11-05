# Plan

The router writes this file from the plan you approved and ticks each step here when it is done. Don't edit it: the router's next write replaces it.

Plan #49 · 2026-10-19 · 2 of 4 steps done
Covers E1–E3

## Steps

- [x] **Step 1.** Make the skeleton: trial.py that prints a help line, and test_trial.py with one test that runs it.
  - Team: route
  - Done when: test_trial.py's test_help passes under python3 -m unittest
  - Why: the smallest thing that runs, so each later step has a test to stand on
  - Covers: none
  - Done by #50
- [x] **Step 2.** Add record_sowing(bed, date) that stores a sowing in trial.json, with a test.
  - Team: route
  - Done when: test_trial.py's test_record_sowing passes, checking a sowing is read back
  - Why: every later step reads the sowings
  - Covers: E1, E2
  - Done by #51
- [ ] **Step 3.** Fetch the week's frost forecast and warn when a sowing falls in a frost window, with a test that fakes the feed.
  - Team: redteam
  - Done when: test_frost.py's test_warns_in_frost_window passes with a faked feed
  - Why: the forecast is the part most likely to be wrong, so it gets attacked
  - Covers: E3
- [ ] **Step 4.** Write the README: how to record a sowing and read the frost warnings.
  - Team: route
  - Done when: README.md names both commands and the test command
  - Why: the volunteers need it
  - Covers: none

## Needs from you

- Key `FROST_FEED_KEY` (step 3): the frost forecast feed
- Account: a frost forecast feed account (step 3)
- Decision: Warn three days or five days before a frost? (step 3)
