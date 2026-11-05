## Steps
1. Make the skeleton: trial.py that prints a help line, and test_trial.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so each later step has a test to stand on
   done when: test_trial.py's test_help passes under python3 -m unittest
   covers: none
2. Add record_sowing(bed, date) that stores a sowing in trial.json, with a test.
   team: route
   why: every later step reads the sowings
   done when: test_trial.py's test_record_sowing passes, checking a sowing is read back
   covers: E1, E2
3. Fetch the week's frost forecast and warn when a sowing falls in a frost window, with a test that fakes the feed.
   team: redteam
   why: the forecast is the part most likely to be wrong, so it gets attacked
   done when: test_frost.py's test_warns_in_frost_window passes with a faked feed
   covers: E3
4. Write the README: how to record a sowing and read the frost warnings.
   team: route
   why: the volunteers need it
   done when: README.md names both commands and the test command
   covers: none

## Needs from you
- key: FROST_FEED_KEY (step 3): the frost forecast feed
- account: a frost forecast feed account (step 3)
- decision: Warn three days or five days before a frost? (step 3)

## Answered
A3: research first would leave the board untested.
B2: the sources matter here.