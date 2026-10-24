# User interviews (Phase 0)

**Goal:** learn how beginners debug and what confuses them. **Not** to sell Kaaran.
**Who:** 5 juniors (1st/2nd year) + 1 lab instructor. 15 minutes each.

## Rules
- Ask about **past behaviour** ("Last time your code was wrong, what did you do?"), not opinions ("Would you use a tool that...?"). People are bad at predicting what they'd use.
- Write down their **exact words** for important answers.
- Don't mention Kaaran until the last question.
- Get permission to take notes; don't record names in this file (use S1, S2...).

## Questions (students)
1. What year/branch are you in? Which language do you use most in labs?
2. Think of the last time your program gave the wrong output. What did you do, step by step?
3. How long did it take to find the problem? Did you find it?
4. Which topics confuse you most when reading code: loops, recursion, lists, functions, pointers, something else?
5. Have you used a debugger, Python Tutor, or ChatGPT to understand code? What was good or frustrating?
6. Do you dry-run code on paper? When and why?
7. *(Show the Kaaran idea in one sentence)* What would you expect it to do? What would make you actually use it?

## Questions (lab instructor)
1. What mistakes do students make most often in labs?
2. How do you currently help a student whose code is wrong? How long does it take?
3. Would comparing a student's code to a reference solution help you? What would you need to see?

---

## Notes

### S1
Year / language: 1st Year CSE, Python
How they debug: Adds print statements after every few lines and checks variable values.
Time to find bug: About 20 minutes.
Confusing topics: Loops and nested loops.
Tools used, and opinion: ChatGPT. Helpful for syntax errors but sometimes explanations are too long.
Quote worth keeping: "I know the output is wrong, but I don't know where the value changed."

### S2
Year / language: 1st Year AIML, Python
How they debug: Runs the code repeatedly and changes small parts until it works.
Time to find bug: 30-40 minutes.
Confusing topics: Functions and parameters.
Tools used, and opinion: ChatGPT and Google. Gets answers quickly but not always the reason.
Quote worth keeping: "I can copy a solution, but I don't understand why mine failed."

### S3
Year / language: 2nd Year CSE, C++
How they debug: Uses VS Code debugger and print statements.
Time to find bug: 15-30 minutes.
Confusing topics: Pointers and references.
Tools used, and opinion: VS Code debugger. Powerful but difficult to understand initially.
Quote worth keeping: "The debugger shows values, but I still don't know what caused the problem."

### S4
Year / language: 1st Year IT, Python
How they debug: Dry-runs code on paper.
Time to find bug: Around 25 minutes.
Confusing topics: Recursion.
Tools used, and opinion: Python Tutor. Visualisation is useful but lacks explanations.
Quote worth keeping: "I can see what happened, but not why it happened."

### S5
Year / language: 2nd Year CSE, C
How they debug: Prints variables and asks classmates for help.
Time to find bug: Sometimes more than an hour.
Confusing topics: Arrays and pointers.
Tools used, and opinion: ChatGPT and online tutorials.
Quote worth keeping: "Most of my time goes into finding where the bug started."
### Instructor
- Common mistakes:
Incorrect loop conditions.
Variable updates in the wrong place.
Function parameter mistakes.
Confusion between copies and references.
Pointer-related mistakes in C/C++.

- How they help now:
Ask students to explain their code line by line.
Use board examples and dry runs.
Examine outputs and intermediate variable values.

- Thoughts on reference comparison:
Could help identify logic differences quickly.
Would be useful if it highlighted where a student's execution differs from the expected execution.
Should explain the reason for the difference, not just show it.

---

## Patterns (fill in after all interviews)
- What did 3+ people say?
Most students use print statements as their primary debugging technique.
Students struggle to understand why values change during execution.
ChatGPT is commonly used but often gives solutions rather than understanding.
Many students find loops, recursion, and references confusing.
Students want explanations, not just error messages.

- What surprised you?
Several students rarely use professional debuggers.
Many students rely on trial-and-error rather than systematic debugging.
Some students spend more time locating a bug than fixing it.
- Does anything change the plan in ROADMAP.md?
The interviews suggest that the highest-priority feature should be the Why Engine, which explains why a specific value was produced. Students appear to need causal explanations more than advanced debugging features. Visual execution tracing and comparison with a reference solution should be prioritised before more advanced features.