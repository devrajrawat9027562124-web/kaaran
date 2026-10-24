# Answer key (for the person running the study: don't show participants)

| Program | Wrong output | Bug line | Reason that counts as correct |
|---|---|---|---|
| `bug1_shopping.py` (warm-up) | 220.0 instead of 270.0 | 6, `discount = discount + 0.1` | The discount grows every round (0.2, then 0.3) instead of staying 0.1 |
| `bug2_backup.py` | backup is `[40, 48, 60]` | 4, `backup = marks` | `backup` and `marks` are the same list, so changing marks changes backup (it needed a copy) |
| `bug3_vowels.py` | 1 instead of 8 | 4, `count = 0` | The counter is reset inside the loop, so only the last character ('e') is counted |

Each expected output was checked by running a corrected version.
