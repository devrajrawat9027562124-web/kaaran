"""LLM explainer: Claude explains one step in plain words, and every value it
mentions is checked against the trace before the student sees it.

Why check: a language model can state a wrong value confidently ("i is 3"
when the trace says 2). The trace is the ground truth, so the model must list
each value it mentions (mentioned_values), and validate() compares that list
with the values Kaaran recorded. A wrong value gets one retry with feedback;
if it is still wrong, the answer is shown marked as unchecked, with the
wrong values listed.

Settings (environment or backend/.env):
    ANTHROPIC_API_KEY   required for this feature; never commit it
    KAARAN_MODEL        default claude-opus-5-5
    KAARAN_EFFORT       default low (short explanations need little thinking)
"""
import hashlib
import json
import os
import re
from collections import OrderedDict

import anthropic

MAX_TOKENS = 4000          # thinking counts toward this too
CACHE_SIZE = 500
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You explain one step of a program run to a first-year programming student, inside Kaaran, a tool that steps through code.

You get the program with line numbers, the step to explain (which line ran and what it did), the variables before and after that line, and sometimes Kaaran's own answer to "why does this variable have this value?" with its chain of causes.

Write two to four short sentences in plain English:
- Say what the line did in this step and how it affects the result.
- Use only values that appear in the facts. Never compute, round or guess a value that isn't listed.
- If the facts suggest a common misconception, such as two names sharing one list, a pointer changing another variable, or a loop starting or stopping one step off, point it out gently.
- Don't rewrite the program and don't give corrected code: the student should find the fix.

In mentioned_values, list every variable value your explanation mentions, with the name and the value written exactly as in the facts."""

SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "mentioned_values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
                "required": ["name", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["explanation", "mentioned_values"],
    "additionalProperties": False,
}


class ExplainerError(Exception):
    """Something the student should see, e.g. a missing key or a refusal."""


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ---------- The prompt ----------

def build_prompt(facts):
    """The facts of one step, as text for the model."""
    lines = facts["code"].splitlines()
    numbered = "\n".join(f"{i:>3} | {text}" for i, text in enumerate(lines, 1))
    line = facts["line"]
    source = lines[line - 1].strip() if 1 <= line <= len(lines) else ""
    parts = [
        f"Language: {facts['language']}",
        f"Program:\n{numbered}",
        f"Step to explain: step {facts['step']}, line {line} `{source}` ({facts['event']} event)",
        f"What Kaaran recorded: {facts['narration']}",
        "Variables before this step:\n" + "\n".join(
            f"  in {frame}: " + (", ".join(f"{k} = {v}" for k, v in values.items()) or "(none)")
            for frame, values in facts["before"].items()),
    ]
    if facts.get("after"):
        parts.append("Variables after this line ran (same function): " +
                     ", ".join(f"{k} = {v}" for k, v in facts["after"].items()))
    if facts.get("output"):
        parts.append(f"Output printed so far:\n{facts['output']}")
    why = facts.get("why")
    if why:
        parts.append(f"The student asked: {why['question']}\nKaaran's answer: {why['summary']}\n"
                     "Chain of causes:\n" + "\n".join(f"  {item}" for item in why["chain"]))
    return "\n\n".join(parts)


# ---------- Checking values ----------

def _normalize(value):
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return re.sub(r"\s+", " ", value)


def known_values(facts):
    """Every (name, value) the trace shows around this step."""
    known = {}
    for values in facts["before"].values():
        for name, value in values.items():
            known.setdefault(name, set()).add(_normalize(value))
    for name, value in (facts.get("after") or {}).items():
        known.setdefault(name, set()).add(_normalize(value))
    why = facts.get("why")
    if why:  # "set total = 3 (using marks = [80, 90, 70], i = 2)": split only before the next "name ="
        pair = re.compile(r"\b([A-Za-z_]\w*) = (.+?)(?=, [A-Za-z_]\w* = |\s*\(| and | because |; |\)|\.?$)")
        for text in [why["summary"]] + list(why["chain"]):
            for name, value in pair.findall(text):
                known.setdefault(name, set()).add(_normalize(value))
    return known


def validate(mentioned, facts):
    """Values the model mentioned that the trace doesn't have."""
    known = known_values(facts)
    problems = []
    for item in mentioned:
        name, value = item["name"].strip(), item["value"]
        if _normalize(value) not in known.get(name, set()):
            problems.append({"name": name, "value": value, "trace_has": sorted(known.get(name, set()))})
    return problems


# ---------- Calling Claude ----------

class Explainer:
    def __init__(self, client=None):
        self.client = client
        self.cache = OrderedDict()

    def _client(self):
        if self.client is None:
            self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self.client

    def explain(self, facts):
        key = hashlib.sha256(json.dumps(facts, sort_keys=True).encode("utf-8")).hexdigest()
        if key in self.cache:
            self.cache.move_to_end(key)
            return dict(self.cache[key], cached=True)

        prompt = build_prompt(facts)
        answer, model = self._ask(prompt)
        problems = validate(answer["mentioned_values"], facts)
        first_attempt = {"mentioned": len(answer["mentioned_values"]), "wrong": len(problems)}
        retried = False
        if problems:
            retried = True
            wrong = "; ".join(f"{p['name']} = {p['value']}" for p in problems)
            feedback = (f"\n\nA previous answer mentioned values that are not in the facts above: {wrong}. "
                        "Write the explanation again using only the values listed above.")
            answer, model = self._ask(prompt + feedback)
            problems = validate(answer["mentioned_values"], facts)

        result = {
            "explanation": answer["explanation"],
            "mentioned_values": answer["mentioned_values"],
            "verified": not problems,
            "problems": problems,
            "retried": retried,
            "first_attempt": first_attempt,  # for measuring the validator's effect
            "model": model,
        }
        self.cache[key] = result
        if len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)
        return dict(result, cached=False)

    def _ask(self, prompt):
        model = os.environ.get("KAARAN_MODEL", "claude-opus-5-5")
        try:
            response = self._client().beta.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA],
                fallbacks="default",  # on a policy decline, retry on Anthropic's recommended model
                cache_control={"type": "ephemeral"},
                output_config={"effort": os.environ.get("KAARAN_EFFORT", "low"),
                               "format": {"type": "json_schema", "schema": SCHEMA}},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError:
            raise ExplainerError("The Anthropic API key in backend/.env isn't valid.")
        except anthropic.RateLimitError:
            raise ExplainerError("Claude is busy (rate limit). Try again in a minute.")
        except anthropic.APIConnectionError:
            raise ExplainerError("Can't reach the Claude API. Check the backend's internet connection.")
        except anthropic.APIStatusError as e:
            raise ExplainerError(f"The Claude API returned an error ({e.status_code}). Try again later.")

        if response.stop_reason == "refusal":
            raise ExplainerError("Claude declined to explain this step.")
        if response.stop_reason == "max_tokens":
            raise ExplainerError("The explanation was cut off. Try again.")
        text = next((block.text for block in response.content if block.type == "text"), None)
        try:
            answer = json.loads(text or "")
        except json.JSONDecodeError:
            raise ExplainerError("Claude's answer wasn't in the expected format. Try again.")
        return answer, getattr(response, "model", model)
