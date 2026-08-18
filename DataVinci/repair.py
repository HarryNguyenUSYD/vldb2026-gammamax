"""NFA-based minimum edit programs for DataVinci regular expressions."""

from __future__ import annotations

import heapq
import re
import sre_parse
from dataclasses import dataclass
from itertools import count
from typing import Callable, Iterable


@dataclass(frozen=True)
class Token:
    label: str
    accepts: Callable[[str], bool]
    choices: tuple[str, ...] = ()

    def emit(self, preferred: str | None = None) -> str:
        if preferred is not None and len(preferred) == 1 and self.accepts(preferred):
            return preferred
        if self.choices:
            return self.choices[0]
        return {"digit": "0", "space": " ", "word": "a", "any": "a"}.get(self.label, "a")

    def emissions(self, preferred: str | None = None) -> tuple[str, ...]:
        if preferred is not None and len(preferred) == 1 and self.accepts(preferred):
            return (preferred,)
        return tuple(dict.fromkeys(self.choices)) or (self.emit(),)


@dataclass(frozen=True)
class Transition:
    source: int
    target: int
    token: Token | None
    edge_id: int


@dataclass
class NFA:
    start: int
    accept: int
    transitions: dict[int, list[Transition]]


@dataclass(frozen=True)
class EditAction:
    kind: str
    source: str | None
    emitted: str | None
    abstract_label: str | None = None
    edge_id: int | None = None


@dataclass(frozen=True)
class EditProgram:
    value: str
    cost: int
    actions: tuple[EditAction, ...]


class UnsupportedRegex(ValueError):
    pass


def _literal(character: str) -> Token:
    return Token(character, lambda value, expected=character: value == expected, (character,))


def _category(category: object) -> Token:
    mapping = {
        sre_parse.CATEGORY_DIGIT: ("digit", str.isdigit, tuple("0123456789")),
        sre_parse.CATEGORY_SPACE: ("space", str.isspace, (" ", "\t")),
        sre_parse.CATEGORY_WORD: ("word", lambda c: c.isalnum() or c == "_", tuple("aA0_")),
        sre_parse.CATEGORY_NOT_DIGIT: ("not_digit", lambda c: not c.isdigit(), ("a", "-")),
        sre_parse.CATEGORY_NOT_SPACE: ("not_space", lambda c: not c.isspace(), ("a", "-")),
        sre_parse.CATEGORY_NOT_WORD: ("not_word", lambda c: not (c.isalnum() or c == "_"), ("-", ".")),
    }
    if category not in mapping:
        raise UnsupportedRegex(f"unsupported regex category: {category}")
    label, predicate, choices = mapping[category]
    return Token(label, predicate, choices)


def _class(items: list[tuple[object, object]]) -> Token:
    predicates: list[Callable[[str], bool]] = []
    choices: list[str] = []
    labels: list[str] = []
    negated = False
    for operation, argument in items:
        if operation is sre_parse.NEGATE:
            negated = True
        elif operation is sre_parse.LITERAL:
            character = chr(argument)
            predicates.append(lambda value, expected=character: value == expected)
            choices.append(character); labels.append(character)
        elif operation is sre_parse.RANGE:
            low, high = map(chr, argument)
            predicates.append(lambda value, lo=low, hi=high: lo <= value <= hi)
            choices.extend((low, high)); labels.append(f"{low}-{high}")
        elif operation is sre_parse.CATEGORY:
            token = _category(argument)
            predicates.append(token.accepts); choices.extend(token.choices); labels.append(token.label)
        else:
            raise UnsupportedRegex(f"unsupported character-class operation: {operation}")
    predicate = lambda value: any(test(value) for test in predicates)
    if negated:
        original = predicate
        predicate = lambda value: not original(value)
        choices = [value for value in ("a", "A", "0", "-", " ") if predicate(value)]
    return Token("[" + "|".join(labels) + "]", predicate, tuple(dict.fromkeys(choices)))


class _Builder:
    def __init__(self) -> None:
        self.next_state = 0
        self.next_edge = 0
        self.transitions: dict[int, list[Transition]] = {}

    def state(self) -> int:
        value = self.next_state; self.next_state += 1
        self.transitions.setdefault(value, [])
        return value

    def add(self, source: int, target: int, token: Token | None) -> None:
        self.transitions[source].append(Transition(source, target, token, self.next_edge))
        self.next_edge += 1

    def compile(self, parsed: Iterable[tuple[object, object]]) -> tuple[int, int]:
        start = self.state(); current = start
        for operation, argument in parsed:
            part_start, part_end = self.operation(operation, argument)
            self.add(current, part_start, None); current = part_end
        end = self.state(); self.add(current, end, None)
        return start, end

    def token_fragment(self, token: Token) -> tuple[int, int]:
        start, end = self.state(), self.state(); self.add(start, end, token)
        return start, end

    def operation(self, operation: object, argument: object) -> tuple[int, int]:
        if operation is sre_parse.LITERAL:
            return self.token_fragment(_literal(chr(argument)))
        if operation is sre_parse.NOT_LITERAL:
            character = chr(argument)
            return self.token_fragment(Token(f"not {character}", lambda value, c=character: value != c,
                                             tuple(v for v in ("a", "0", "-") if v != character)))
        if operation is sre_parse.ANY:
            return self.token_fragment(Token("any", lambda value: value != "\n", ("a",)))
        if operation is sre_parse.IN:
            return self.token_fragment(_class(list(argument)))
        if operation is sre_parse.CATEGORY:
            return self.token_fragment(_category(argument))
        if operation is sre_parse.SUBPATTERN:
            return self.compile(argument[-1])
        if operation is sre_parse.AT:
            start, end = self.state(), self.state(); self.add(start, end, None); return start, end
        if operation is sre_parse.BRANCH:
            start, end = self.state(), self.state()
            for branch in argument[1]:
                branch_start, branch_end = self.compile(branch)
                self.add(start, branch_start, None); self.add(branch_end, end, None)
            return start, end
        if operation in (sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT):
            minimum, maximum, child = argument
            start = self.state(); current = start
            for _ in range(minimum):
                child_start, child_end = self.compile(child)
                self.add(current, child_start, None); current = child_end
            end = self.state()
            if maximum == sre_parse.MAXREPEAT:
                self.add(current, end, None)
                child_start, child_end = self.compile(child)
                self.add(current, child_start, None); self.add(child_end, current, None)
            else:
                for _ in range(maximum - minimum):
                    self.add(current, end, None)
                    child_start, child_end = self.compile(child)
                    self.add(current, child_start, None); current = child_end
                self.add(current, end, None)
            return start, end
        raise UnsupportedRegex(f"unsupported regex operation: {operation}")


def compile_regex(expression: str) -> NFA:
    try:
        parsed = sre_parse.parse(expression.replace(r"\z", r"\Z"))
    except re.error as error:
        raise UnsupportedRegex(str(error)) from error
    builder = _Builder()
    start, accept = builder.compile(parsed)
    return NFA(start, accept, builder.transitions)


def _shortest_programs(source: str, nfa: NFA, limit: int,
                       preferred_by_edge: dict[int, str] | None) -> list[EditProgram]:
    start = (0, nfa.start)
    distances = {start: 0}
    predecessors: dict[tuple[int, int], list[tuple[tuple[int, int], EditAction | None]]] = {start: []}
    queue: list[tuple[int, int, tuple[int, int]]] = [(0, 0, start)]
    sequence = count(1)
    best_accept: int | None = None

    def relax(previous, current, new_cost, action):
        old = distances.get(current)
        if old is None or new_cost < old:
            distances[current] = new_cost
            predecessors[current] = [(previous, action)]
            heapq.heappush(queue, (new_cost, next(sequence), current))
        elif new_cost == old and (previous, action) not in predecessors[current]:
            predecessors[current].append((previous, action))

    while queue:
        cost, _, node = heapq.heappop(queue)
        if cost != distances[node] or (best_accept is not None and cost > best_accept):
            continue
        index, state = node
        if index == len(source) and state == nfa.accept:
            best_accept = cost
            continue
        if index < len(source):
            character = source[index]
            relax(node, (index + 1, state), cost + 1,
                  EditAction("delete", character, None))
        for transition in nfa.transitions.get(state, ()):
            target = (index, transition.target)
            if transition.token is None:
                relax(node, target, cost, None)
                continue
            token = transition.token
            emissions = token.emissions((preferred_by_edge or {}).get(transition.edge_id))
            for emitted in emissions:
                relax(node, target, cost + 1,
                      EditAction("insert", None, emitted, token.label, transition.edge_id))
            if index < len(source):
                character = source[index]
                matches = token.accepts(character)
                if matches:
                    relax(node, (index + 1, transition.target), cost,
                          EditAction("match", character, character, token.label, transition.edge_id))
                else:
                    for emitted in emissions:
                        relax(node, (index + 1, transition.target), cost + 1,
                              EditAction("substitute", character, emitted,
                                         token.label, transition.edge_id))

    accept = (len(source), nfa.accept)
    if accept not in distances:
        return []
    paths: list[tuple[EditAction, ...]] = []

    def backtrack(node: tuple[int, int], actions: list[EditAction], active: set[tuple[int, int]]) -> None:
        if len(paths) >= limit or node in active:
            return
        if node == start:
            paths.append(tuple(reversed(actions))); return
        active.add(node)
        for previous, action in predecessors.get(node, ()):
            if action is None:
                backtrack(previous, actions, active)
            else:
                actions.append(action); backtrack(previous, actions, active); actions.pop()
        active.remove(node)

    backtrack(accept, [], set())
    programs = []
    for actions in paths:
        value = "".join(action.emitted or "" for action in actions if action.kind != "delete")
        programs.append(EditProgram(value, distances[accept], actions))
    unique = {program.value: program for program in programs}
    return sorted(unique.values(), key=lambda program: (program.cost, program.value))[:limit]


def repair_regex(source: str, expression: str, max_edits: int | None = None, limit: int = 100,
                 preferred_by_edge: dict[int, str] | None = None) -> list[EditProgram]:
    programs = _shortest_programs(source, compile_regex(expression), limit, preferred_by_edge)
    if max_edits is not None:
        programs = [program for program in programs if program.cost <= max_edits]
    return programs


def matching_trace(expression: str, value: str) -> tuple[tuple[int, str, str], ...] | None:
    programs = repair_regex(value, expression, max_edits=0, limit=1)
    if not programs:
        return None
    return tuple((action.edge_id, action.abstract_label or "", action.emitted)
                 for action in programs[0].actions
                 if action.kind == "match" and action.edge_id is not None and action.emitted is not None)
