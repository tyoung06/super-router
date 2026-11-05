## Steps
1. Make the skeleton: swap.py that prints a help line, and test_swap.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so each later step has a test to stand on
   done when: test_swap.py's test_help passes under python3 -m unittest
2. Add offer(packet, grower) that records an offer in swaps.json, with a test.
   team: route
   why: every later step reads the offers
   done when: test_swap.py's test_offer passes, checking an offer is read back
3. Match offers to wants and print the swaps, with a test that fakes two growers.
   team: redteam
   why: the matching is the part most likely to be wrong, so it gets attacked
   done when: test_match.py's test_two_growers passes with faked offers
4. Write the README: how to offer a packet and read the matches.
   team: route
   why: the growers need it
   done when: README.md names both commands and the test command

## Needs from you
- test command: python3 -m unittest

## Answered
A3: research first would leave the board untested.
B2: the sources matter here.