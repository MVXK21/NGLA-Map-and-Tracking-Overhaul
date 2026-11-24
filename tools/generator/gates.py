"""Work out when a scripted door exists.

Many doors are enabled and disabled by their mwscript as quests progress:
Raven Rock's buildings appear with the ColonyState variable, Stronghold manors
with the Stronghold variable, and so on. compile_script() turns such a script
into rules the mod evaluates at runtime against the real game state.

A script compiles to an ordered list of rules. Every rule whose conditions all
hold sets the door's visibility, or stops evaluation (a mwscript Return):

    {"c": [("g", "colonystate", "<", 3)], "v": False, "s": False}

Condition kinds: "g" = global variable, "j" = journal index. Tests that only
matter while the script runs (GetDisabled, CellChanged, MenuMode) don't decide
what the door's state should be, so they are ignored. A script that decides on
anything else (local variables, GetDeadCount...) returns None: its door stays
on the map rather than risk hiding a real place.
"""
from __future__ import annotations

import re

_IF = re.compile(r"^(if|elseif)\b\s*(.*)$", re.I)
_JOURNAL = re.compile(r'^getjournalindex\s*,?\s*"?([^"\s,]+)"?\s*(==|!=|<=|>=|=|<|>)\s*(-?\d+(?:\.\d+)?)$', re.I)
_COMPARE = re.compile(r'^"?([A-Za-z_][\w]*)"?\s*(==|!=|<=|>=|=|<|>)\s*(-?\d+(?:\.\d+)?)$')
_WILD = re.compile(r"^(getdisabled|cellchanged|menumode)\b", re.I)
_BARE = re.compile(r"^[A-Za-z_]\w*$")
_NEGATE = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}

WILD = "wild"       # a test that doesn't decide the door's state
UNKNOWN = "unknown"


def _strip_parens(s: str) -> str:
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        for i, ch in enumerate(s):
            depth += (ch == "(") - (ch == ")")
            if depth == 0 and i < len(s) - 1:
                return s          # the first "(" closes before the end: not one outer pair
        s = s[1:-1].strip()
    return s


def _number(text: str):
    v = float(text)
    return int(v) if v == int(v) else v


def parse_condition(text: str, global_names: set[str]):
    s = _strip_parens(text)
    if _WILD.match(s):
        return WILD
    m = _JOURNAL.match(s)
    if m:
        op = "==" if m.group(2) == "=" else m.group(2)
        return ("j", m.group(1).lower(), op, _number(m.group(3)))
    m = _COMPARE.match(s)
    if m and m.group(1).lower() in global_names:
        op = "==" if m.group(2) == "=" else m.group(2)
        return ("g", m.group(1).lower(), op, _number(m.group(3)))
    if _BARE.match(s) and s.lower() in global_names:
        return ("g", s.lower(), "!=", 0)
    return UNKNOWN


def _negated(cond):
    return (cond[0], cond[1], _NEGATE[cond[2]], cond[3])


class _Frame:
    """One if / elseif / else chain."""

    def __init__(self, base: list, poisoned: bool, wild: bool):
        self.base = base            # conditions of the enclosing branch
        self.base_poisoned = poisoned
        self.base_wild = wild
        self.priors: list = []      # earlier branches' conditions in this chain
        self.conds, self.poisoned, self.wild = base, poisoned, wild

    def branch(self, cond):
        """Enter a branch; cond None = else."""
        conds = list(self.base)
        poisoned, wild = self.base_poisoned, self.base_wild
        for p in self.priors:
            if p == UNKNOWN:
                poisoned = True
            elif p != WILD:
                conds.append(_negated(p))
        if cond == UNKNOWN:
            poisoned = True
        elif cond == WILD:
            wild = True
        elif cond is not None:
            conds.append(cond)
        if cond is not None:
            self.priors.append(cond)
        self.conds, self.poisoned, self.wild = conds, poisoned, wild


def compile_script(text: str, global_names: set[str]):
    """Rules for a door script, or None if its state can't be worked out."""
    rules: list[dict] = []
    stack = [_Frame([], False, False)]
    for raw in text.splitlines():
        line = raw.split(";")[0].strip()
        if not line:
            continue
        low = line.lower()
        m = _IF.match(line)
        if m:
            cond = parse_condition(m.group(2), global_names)
            if m.group(1).lower() == "if":
                top = stack[-1]
                stack.append(_Frame(top.conds, top.poisoned, top.wild))
            stack[-1].branch(cond)
        elif low == "else":
            stack[-1].branch(None)
        elif low == "endif":
            if len(stack) > 1:
                stack.pop()
        elif low in ("disable", "enable"):
            top = stack[-1]
            if top.poisoned:
                return None
            rules.append({"c": list(top.conds), "v": low == "enable", "s": False})
        elif low == "return":
            top = stack[-1]
            if not top.poisoned and not top.wild:
                rules.append({"c": list(top.conds), "v": None, "s": True})
    if not any(r["v"] is False for r in rules):
        return None                 # never hides itself
    return rules
