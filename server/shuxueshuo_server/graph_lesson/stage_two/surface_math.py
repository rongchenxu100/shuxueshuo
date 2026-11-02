"""Small, bounded reader for textbook formulae, with no Python evaluation.

This reader is deliberately narrower than mathematical notation: rational
polynomials, declared names, and already-read unary functions suffice for D1.
Unsupported syntax is omitted rather than guessed or simplified unsafely.
"""

import re
from dataclasses import dataclass, field

import sympy as sp

from ...problem_understanding.notation_semantics import bounded_expand


@dataclass
class Surface:
    text: str
    offsets: list[tuple[int, int]]
    wrappers: list[tuple[int, int, int, int]] = field(default_factory=list)

    def original_span(self, start, end):
        original_start, original_end = self.offsets[start][0], self.offsets[end - 1][1]
        for first, last, begin, finish in self.wrappers:
            # A formula containing a wrapped atom includes its complete TeX
            # spelling. A word inside a longer prose wrapper remains a word.
            if start <= first < last <= end:
                original_start, original_end = min(original_start, begin), max(original_end, finish)
        return original_start, original_end


_COMMANDS = {
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "lt": "<", "gt": ">", "ne": "≠", "neq": "≠",
    "forall": "∀", "exists": "∃", "in": "∈", "infty": "∞", "neg": "¬", "lnot": "¬",
    "mid": "|", "vert": "|", "cdot": "*", "times": "*",
    "left": "", "right": "", "quad": " ", "qquad": " ",
}
_CHARACTERS = {"−": "-", "²": "^2", "³": "^3", "（": "(", "）": ")"}
_MATH = set("()[]{}+-*/^=<>|∞ℝ∈≤≥≠∀∃¬_'¤")


def normalize_surface(text, start=0, end=None):
    """Normalize display tokens before segmentation, keeping original offsets."""
    end = len(text) if end is None else end
    chars, offsets, wrappers = [], [], []

    def emit(value, begin, finish):
        chars.extend(value)
        offsets.extend([(begin, finish)] * len(value))

    def read(begin, finish):
        i = begin
        while i < finish:
            if text[i] != "\\":
                emit(_CHARACTERS.get(text[i], text[i]), i, i + 1)
                i += 1
                continue
            real = re.match(r"\\mathbb(?:\{R\}|\s+R)", text[i:finish])
            wrapper = re.match(r"\\(?:text|mathrm)\{([^{}]*)\}", text[i:finish])
            command = re.match(r"\\([A-Za-z]+)", text[i:finish])
            if real:
                emit("ℝ", i, i + real.end())
                i += real.end()
            elif wrapper:
                first = len(chars)
                read(i + wrapper.start(1), i + wrapper.end(1))
                last = len(chars)
                while first < last and chars[first].isspace():
                    first += 1
                while last > first and chars[last - 1].isspace():
                    last -= 1
                if first < last:
                    wrappers.append((first, last, i, i + wrapper.end()))
                i += wrapper.end()
            elif command:
                word = command.group(1)
                stop = i + command.end()
                if word not in _COMMANDS and stop < finish and text[stop] == "{":
                    depth = 1
                    stop += 1
                    while stop < finish and depth:
                        depth += (text[stop] == "{") - (text[stop] == "}")
                        stop += 1
                # A sentinel stays inside the candidate run and makes parsing
                # fail; an unknown command must not turn into a variable.
                emit(_COMMANDS.get(word, "¤"), i, stop)
                i = stop
            elif i + 1 < finish and text[i + 1] in ",;! ":
                emit(" ", i, i + 2)
                i += 2
            elif i + 1 < finish and text[i + 1] in "()[]":
                emit("$", i, i + 2)
                i += 2
            elif i + 1 < finish and text[i + 1] in "{}":
                emit(text[i + 1], i, i + 2)
                i += 2
            else:
                emit("¤", i, min(i + 2, finish))
                i += 2

    read(start, end)
    return Surface("".join(chars), offsets, wrappers)


def _math_char(char):
    return (char.isascii() and char.isalnum()) or char in _MATH


def formula_spans(text):
    """Yield runs and split only top-level mathematical comma/colon separators."""
    i = 0
    while i < len(text):
        if not _math_char(text[i]):
            i += 1
            continue
        start = i
        while i < len(text):
            if _math_char(text[i]):
                i += 1
            elif text[i].isspace():
                j = i
                while j < len(text) and text[j].isspace():
                    j += 1
                if j < len(text) and _math_char(text[j]):
                    i = j
                else:
                    break
            elif text[i] in ".,;:":
                left, right = i - 1, i + 1
                while left >= start and text[left].isspace():
                    left -= 1
                while right < len(text) and text[right].isspace():
                    right += 1
                if left >= start and right < len(text) and _math_char(text[left]) and _math_char(text[right]):
                    i += 1
                else:
                    break
            else:
                break
        stop, depth, part = i, 0, start
        for j in range(start, stop):
            char = text[j]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char in ",;:" and depth == 0:
                yield from _trimmed(text, part, j)
                part = j + 1
        yield from _trimmed(text, part, stop)


def _trimmed(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        yield start, end


def split_relation(text):
    """Return a single top-level relation; chains are handled as domains only."""
    depth, found, i = 0, [], 0
    while i < len(text):
        c = text[i]
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif c in "<>=≤≥" and depth == 0:
            op = {"≤": "<=", "≥": ">="}.get(c, c)
            length = 1
            if c in "<>" and text[i + 1:i + 2] == "=":
                op, length = c + "=", 2
            found.append((i, length, op))
            i += length - 1
        i += 1
    if depth or len(found) != 1:
        raise ValueError("single balanced relation required")
    i, length, op = found[0]
    return text[:i], op, text[i + length:]


class PolynomialReader:
    """Recursive descent into SymPy constructors, never eval/parse_expr/sympify."""

    def __init__(self, names, aliases=None, functions=None):
        self.names = set(names)
        self.aliases = aliases if aliases is not None else {}
        self.functions = functions if functions is not None else {}
        self.ambiguous_names = set()

    @staticmethod
    def _guard(value):
        if sp.count_ops(value) > 512:
            raise ValueError("formula operation limit")
        for number in value.atoms(sp.Rational):
            if max(abs(int(number.p)).bit_length(), int(number.q).bit_length()) > 2048:
                raise ValueError("formula integer size limit")
        for power in value.atoms(sp.Pow):
            if power.exp.is_Integer and abs(power.exp) > 32:
                raise ValueError("formula degree limit")
        return value

    def parse(self, text):
        if len(text) > 2048:
            raise ValueError("formula length limit")
        raw = re.findall(r"(?:\d+(?:\.\d+)?|[A-Za-z][A-Za-z0-9_]*|\*\*|[^\s])", text)
        tokens = []
        for token in raw:
            if (re.fullmatch(r"[A-Za-z]+", token)
                    and token not in self.names | self.aliases.keys() | self.functions.keys()
                    and len(token) > 1 and all(letter in self.names for letter in token)):
                tokens.extend(token)
                continue
            tokens.append(token)
        if not tokens or len(tokens) > 256:
            raise ValueError("formula token limit")
        self.tokens, self.index, self.depth = tokens, 0, 0
        result = self._sum()
        if self.index != len(tokens):
            raise ValueError("unsupported formula token")
        return bounded_expand(result)

    def _peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else ""

    def _sum(self):
        result = self._product()
        while self._peek() in ("+", "-"):
            op = self._peek()
            self.index += 1
            right = self._product()
            result = self._guard(result + right if op == "+" else result - right)
        return result

    def _product(self):
        result = self._unary()
        while True:
            token = self._peek()
            implicit = bool(token) and (token[0].isalnum() or token in ("(", "{"))
            if token not in ("*", "/") and not implicit:
                return result
            if not implicit:
                self.index += 1
            right = self._unary()
            if token == "/":
                if not right.is_Rational or right == 0:
                    raise ValueError("variable or zero denominator is unsupported")
                result = self._guard(result / right)
            else:
                result = self._guard(result * right)

    def _unary(self):
        if self._peek() in ("+", "-"):
            op = self._peek()
            self.index += 1
            self.depth += 1
            if self.depth > 24:
                raise ValueError("formula depth limit")
            result = self._unary()
            self.depth -= 1
            return result if op == "+" else -result
        return self._power()

    def _power(self):
        result = self._atom()
        if self._peek() in ("^", "**"):
            self.index += 1
            power = self._atom()
            if not power.is_Integer or not 0 <= power <= 8:
                raise ValueError("only small nonnegative integer powers are supported")
            result = self._guard(result ** int(power))
        return result

    def _atom(self):
        token = self._peek()
        self.index += 1
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            if len(token) > 24:
                raise ValueError("number length limit")
            if "." in token:
                whole, fraction = token.split(".")
                return sp.Rational(int(whole + fraction), 10 ** len(fraction))
            return sp.Integer(int(token))
        if token in ("(", "{"):
            self.depth += 1
            if self.depth > 24:
                raise ValueError("formula depth limit")
            result = self._sum()
            if self._peek() != {"(": ")", "{": "}"}[token]:
                raise ValueError("unbalanced formula")
            self.index += 1
            self.depth -= 1
            return result
        if token in self.functions:
            if self._peek() != "(":
                raise ValueError("function argument required")
            argument = self._atom()
            formal, body = self.functions[token]
            return self._guard(body.xreplace({sp.Symbol(formal, real=True): argument}))
        if token in self.aliases:
            return self.aliases[token]
        if token in self.names:
            return sp.Symbol(token, real=True)
        raise ValueError("unknown name or unsupported formula")


def equivalent(left, right):
    return bounded_expand(left - right) == 0
