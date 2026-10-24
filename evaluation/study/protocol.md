# User study protocol (Phase 8)

A plan for **you** to run. Nothing here has been run yet, and no results exist until you collect them.

## Question

Do beginners find the cause of a bug faster, and more often, with Kaaran than with the tool they'd otherwise use?

## Before you start

- Show this plan to your project guide, and ask whether the department needs approval for a study with students.
- Participation is voluntary, it doesn't affect anyone's marks, and anyone can stop at any time.
- Read out the consent statement below and note each participant's agreement.
- Record no names: use codes P01, P02, … in every file.

> *"This is a test of a debugging tool, not a test of you. We'll time how long it takes to find a bug in three short programs and ask a few questions afterwards. Your name won't be recorded, it doesn't affect any marks, and you can stop at any time. Is that OK?"*

## Participants

10–15 first-year students who have finished a first course in Python. Note each person's year, branch and how often they program (from the feedback form). Fewer than 10 is too few to say anything beyond "in these few cases".

## Design: everyone tries both tools

| | Program A | Program B |
|---|---|---|
| Half the participants (odd P numbers) | Kaaran | Baseline |
| The other half (even P numbers) | Baseline | Kaaran |

- **Baseline:** [Python Tutor](https://pythontutor.com) plus print statements, which is what students already use (see `docs/interviews.md`).
- **Programs:** `bug1_shopping.py` is a warm-up for everyone (with Kaaran, 3 minutes, not scored), so nobody's first contact with Kaaran is timed. A = `bug2_backup.py`, B = `bug3_vowels.py`. Swap A and B for every other pair of participants, so neither program always goes with one tool.
- Each person tries both tools, which halves the number of people you need. The order is balanced, so "getting better with practice" doesn't favour one tool.

## Each task

1. Give the program and say what it should print (the comment at the top).
2. Say: *"Find the line that causes the wrong output and tell me why it happens. Don't fix it."*
3. Start the timer. Stop when they name the line and give a reason, or at **8 minutes**.
4. Record the time, the line they named, and their reason (a few words).

Don't help during the task. If they're stuck with the tool itself (not the bug), you may answer one "how do I…" question; note it.

## What counts as success

Both are needed: the right line, and a reason that matches the answer key (`answers.md`). Keep the answer key away from participants.

## After both tasks

The feedback form (`feedback_form.md`), about 5 minutes.

## Recording

One row per participant per task in `results_template.csv` (save a copy as `results.csv`). Keep the raw notes.

## Analysing honestly

- For each tool, report the number of successes out of n, the median time (with the 8-minute cap counted as 8), and each person's time difference (Kaaran minus baseline).
- With about 12 people, describe the numbers rather than claim significance. If you do run a test, use the Wilcoxon signed-rank test on the paired times and report the effect size, not just p.
- Report where Kaaran did **worse** or made no difference, and what confused people. A small, honest result is a good report; an overclaimed one is not.
- Limits to state:
  - few participants, all from one college;
  - you built the tool and also ran the study (possible bias);
  - short, artificial programs;
  - novelty: people may like a new tool just because it's new.
