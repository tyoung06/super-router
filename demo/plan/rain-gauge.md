# Plan

The router writes this file from the plan you approved and ticks each step here when it is done. Don't edit it: the router's next write replaces it.

Plan #57 · 2026-10-19 · 1 of 3 steps done

## Steps

- [x] **Step 1.** Make the skeleton: gauge.py that prints a help line, and test_gauge.py with one test that runs it.
  - Team: route
  - Done when: test_gauge.py's test_help passes under python3 -m unittest
  - Why: the smallest thing that runs
  - Done by #58
- [ ] **Step 2.** Add record(mm, date) that stores a reading in gauge.json, with a test.
  - Team: route
  - Done when: test_gauge.py's test_record passes, checking a reading is read back
  - Why: every later step reads the readings
- [ ] **Step 3.** Add a weekly total and a README that says how to run the tests.
  - Team: route
  - Done when: test_gauge.py's test_weekly passes; README.md names the test command
  - Why: what the allotment wants to see

## Needs from you

None.
