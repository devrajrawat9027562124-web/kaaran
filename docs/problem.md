# Kaaran: Problem statement

> Fill this in **after** the interviews and the related-work check. Use evidence from
> `interviews.md` and `related-work.md`. Delete the guiding questions when done.

## Target user
Kaaran is aimed for all undergraduate students learning Python programming, either in introductory programming labs or through self-study. These students are still developing their understanding of variables, control flow, functions, recursion, and references. Many struggle to understand not only that their code is wrong, but also why it behaves as it does.

At our university, this includes students enrolled in introductory programming courses where Python is taught as a first programming language.

## Problem
When beginner programmers encounter an error or unexpected output, they often rely on trial-and-error debugging rather than understanding the root cause of the problem. Interview participants reported spending significant amounts of time stepping through code, searching online, or repeatedly modifying code without understanding what the program was actually doing.
Many students misunderstand concepts such as variable assignment, function calls, recursion, loop execution, and object references. These misconceptions lead to frustration and increase the time required to identify and fix bugs. As a result, students often learn how to patch an issue without actually understanding the underlying program behaviour.

## Existing tools and their gaps
Python Tutor

Python Tutor visualises program execution step-by-step and clearly shows stack frames, variables, and object references. It is especially useful for demonstrating recursion and aliasing. However, it does not explain why a particular value exists or answer causal questions about program behaviour. It also cannot compare a student's solution against a correct implementation.

Thonny Debugger

Thonny provides a beginner-friendly debugger with variable inspection and line-by-line execution. Students can observe program state changes easily. However, explanations are limited and students must identify causes themselves.

IDE Debuggers (VS Code)

Professional debuggers provide breakpoints, watches, call stacks, and advanced debugging capabilities. However, these tools are designed primarily for software developers rather than novice learners and assume familiarity with debugging concepts.

ChatGPT and LLM-Based Tools

Large language models can explain code in natural language and answer programming questions interactively. However, they do not automatically have access to the exact execution trace of a student's program and may produce explanations that are incomplete or incorrect. They also do not provide precise execution visualisations.

Overall, existing tools offer either:

execution visualisation,
debugging support, or
natural-language explanations,

but no tool combines all three in a way specifically designed for novice programmers.

## How Kaaran is different
Kaaran combines execution tracing, dynamic program analysis, and natural-language explanations in a single learning tool.

Unlike existing visualisers and debuggers, Kaaran's Why Engine allows students to ask questions such as "Why is this variable equal to 10?" and receive a direct explanation based on the executed program. It can also compare a student's behaviour against a reference solution, helping students identify both mistakes and misconceptions more effectively.

## How success will be measured
The project will be considered successful if students using Kaaran can:

Identify bugs faster than students using traditional debugging tools.
Correctly explain why a program produced a particular output.
Achieve a higher bug-fixing success rate.
Accurately identify the statements responsible for a value produced during execution.
Report greater confidence in understanding program behaviour.

Possible evaluation metrics include:

Average time to locate a bug.
Percentage of bugs correctly fixed.
Accuracy of generated slices/explanations.
Student understanding scores from post-task questionnaires.

The project will be considered unsuccessful if students using Kaaran show little or no improvement compared to existing approaches, or if the generated explanations fail to correctly identify the causes of program behaviour.

## Scope
The initial version of Kaaran focuses on explaining the behaviour of small Python programs used in introductory programming courses. The system is designed with future support for C and C++ so that students can also receive explanations for concepts such as pointers, memory management, and data structures.
