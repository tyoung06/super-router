## Steps
2. Add record(mm, date, bed) that stores a reading per bed in gauge.json, with a test.
   team: route
   why: the idea asks for a reading per bed, so the store takes the bed from here on
   done when: test_gauge.py's test_record passes, checking a reading is read back for its bed
3. Add a weekly total per bed, with a test.
   team: route
   why: the total follows the store
   done when: test_gauge.py's test_weekly passes for two beds
4. Write the README: how to record a reading and read the weekly totals.
   team: route
   why: what the allotment needs
   done when: README.md names both commands and the test command

## Needs from you
none

## Changed
step 2: it now takes the bed, as the idea asks
step 3: the weekly total is per bed, and the README moved to its own step