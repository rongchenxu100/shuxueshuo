"""Bounded scalar mathematics syntax. Parsing never proves or registers a fact.

Offsets are Unicode code-point offsets into the *original* source. Display and
canonical trees are immutable; SymPy is constructed only by explicit conversion,
with caller-owned Symbols. No Python or general LaTeX parser is involved.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from math import isqrt

import sympy as sp

Span = tuple[int, int]
RELATIONS = {"=", "!=", ">", "<", ">=", "<="}
SCALAR_OPS = {
    "integer",
    "symbol",
    "group",
    "pos",
    "neg",
    "add",
    "sub",
    "mul",
    "div",
    "pow",
    "sqrt",
}
BINARY = {"+": "add", "-": "sub", "*": "mul", "/": "div", "^": "pow", "±": "pm"}
PRECEDENCE = {"±": 10, "+": 10, "-": 10, "*": 20, "/": 20, "^": 30}
NAME = re.compile(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*")
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
SUPER_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"


class MathParseError(ValueError):
    def __init__(
        self, code, message, *, source, span, path="n", source_path=None, step=None
    ):
        self.code, self.source, self.span = code, source, span
        self.message = message
        self.path, self.source_path, self.step = path, source_path, step
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class MathNode:
    op: str
    span: Span
    children: tuple[MathNode, ...] = ()
    text: str | None = None
    operator_span: Span | None = None
    path: str = "n"
    synthetic: bool = False
    branch_id: str | None = None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class DomainObligation:
    operator: str
    expression: MathNode
    node_path: str
    span: Span
    status: str = "unverified"


@dataclass(frozen=True)
class ParsedMath:
    source: str
    normalized_source: str
    source_map: tuple[Span, ...]
    tree: MathNode
    ast: MathNode
    obligations: tuple[DomainObligation, ...]
    source_path: str | None = None
    step: int | None = None
    related_step: int | None = None

    def to_sympy(self, symbols: Mapping[str, sp.Symbol]):
        """Explicit lowering of scalar expressions/single relations only.

        Domain obligations are still unverified after lowering. The result is
        a computational representation, never permission to execute a Method.
        """
        if self.ast.op not in SCALAR_OPS | RELATIONS:
            raise MathParseError(
                "not_single_value",
                "该语法不能转换为单个计算值",
                source=self.source,
                span=self.ast.span,
                source_path=self.source_path,
                step=self.step,
            )
        for node in self.ast.walk():
            if node.op == "symbol" and not isinstance(
                symbols.get(node.text), sp.Symbol
            ):
                raise MathParseError(
                    "unknown_symbol",
                    f"未知标量 {node.text}",
                    source=self.source,
                    span=node.span,
                    path=node.path,
                    source_path=self.source_path,
                    step=self.step,
                )
        return _sympy(self.ast, symbols)


@dataclass(frozen=True)
class _Token:
    text: str
    span: Span
    synthetic: bool = False


def _paths(node, path="n"):
    return replace(
        node,
        path=path,
        children=tuple(_paths(c, f"{path}.{i}") for i, c in enumerate(node.children)),
    )


def _ungroup(node):
    while node.op == "group":
        node = node.children[0]
    return node


def _integer(node):
    node = _ungroup(node)
    if node.op == "integer":
        return int(node.text)
    if node.op in {"neg", "pos"}:
        child = _ungroup(node.children[0])
        if child.op == "integer":
            return (-1 if node.op == "neg" else 1) * int(child.text)
    return None


def _constant_value(node, children):
    """Compute exact rational constants after this node passes syntax/size guards.

    Children have already been checked and evaluated. No floats, symbolic
    simplification or SymPy construction; trees and exponent syntax stay intact.
    Non-rational roots and expressions containing symbols remain unknown.
    """
    if node.op == "integer":
        return Fraction(node.text)
    if not children or any(value is None for value in children):
        return None
    if node.op in {"group", "pos"}:
        return children[0]
    if node.op == "neg":
        return -children[0]
    if node.op in {"add", "sub", "mul", "div", "pow"}:
        left, right = children
        if node.op == "add":
            return left + right
        if node.op == "sub":
            return left - right
        if node.op == "mul":
            return left * right
        if node.op == "div":
            return left / right
        # check() admits only bounded integer literal exponents before this call.
        return left ** int(right)
    if node.op == "sqrt":
        value = children[0]
        numerator, denominator = isqrt(value.numerator), isqrt(value.denominator)
        if numerator**2 == value.numerator and denominator**2 == value.denominator:
            return Fraction(numerator, denominator)
    return None


def _canonical(node, sign=None):
    if node.op == "group":
        return _canonical(node.children[0], sign)
    children = tuple(_canonical(c, sign) for c in node.children)
    if node.op == "pm":
        op = (
            ("pos" if sign == "+" else "neg")
            if len(children) == 1
            else ("add" if sign == "+" else "sub")
        )
        return replace(node, op=op, text=sign, children=children)
    return replace(node, children=children)


def _sympy(node, symbols):
    if node.op == "integer":
        return sp.Integer(node.text)
    if node.op == "symbol":
        return symbols[node.text]
    args = [_sympy(c, symbols) for c in node.children]
    constructors = {
        "pos": lambda x: x,
        "neg": lambda x: -x,
        "add": lambda x, y: x + y,
        "sub": lambda x, y: x - y,
        "mul": lambda x, y: x * y,
        "div": lambda x, y: x / y,
        "pow": lambda x, y: x**y,
        "sqrt": sp.sqrt,
        "=": lambda x, y: sp.Eq(x, y, evaluate=False),
        "!=": lambda x, y: sp.Ne(x, y, evaluate=False),
        ">": lambda x, y: sp.Gt(x, y, evaluate=False),
        "<": lambda x, y: sp.Lt(x, y, evaluate=False),
        ">=": lambda x, y: sp.Ge(x, y, evaluate=False),
        "<=": lambda x, y: sp.Le(x, y, evaluate=False),
    }
    return constructors[node.op](*args)


def _render(node):
    """One original-source interval per emitted normalized character."""
    chunks, mapping = [], []

    def emit(text, span):
        chunks.append(text)
        mapping.extend([span] * len(text))

    def visit(n):
        op_span = n.operator_span or n.span
        if n.op in {"integer", "symbol", "binding"}:
            emit(n.text, n.span)
        elif n.op == "group":
            emit("(", (n.span[0], n.span[0] + 1))
            visit(n.children[0])
            emit(")", (n.span[1] - 1, n.span[1]))
        elif n.op in {"pos", "neg", "sqrt"} or (n.op == "pm" and len(n.children) == 1):
            emit({"pos": "+", "neg": "-", "sqrt": "sqrt", "pm": "±"}[n.op], op_span)
            emit("(", op_span)
            visit(n.children[0])
            emit(")", op_span)
        elif n.op == "definition":
            visit(n.children[0])
            emit(":=", op_span)
            visit(n.children[1])
        elif n.op in {"premise", "conclusion"}:
            emit("∵" if n.op == "premise" else "∴", op_span)
            for i, child in enumerate(n.children):
                if i:
                    emit(",", (n.children[i - 1].span[1], child.span[0]))
                visit(child)
        else:
            symbol = {
                "add": "+",
                "sub": "-",
                "mul": "*",
                "div": "/",
                "pow": "^",
                "pm": "±",
                "definition": ":=",
            }.get(n.op, n.op)
            emit("(", (n.span[0], n.span[0]))
            visit(n.children[0])
            emit(symbol, op_span)
            visit(n.children[1])
            emit(")", (n.span[1], n.span[1]))

    visit(node)
    return "".join(chunks), tuple(mapping)


class _Parser:
    def __init__(self, source, symbols, *, legacy=False, source_path=None, step=None):
        self.source, self.symbols = source, symbols
        self.legacy, self.source_path, self.step = legacy, source_path, step
        if not isinstance(source, str) or not source.strip() or len(source) > 1024:
            self.fail(
                "invalid_expression",
                "表达式应为 1–1024 个字符",
                (0, len(source) if isinstance(source, str) else 0),
            )
        self.tokens = self.lex()
        self.i, self.depth, self.count = 0, 0, 0

    def fail(self, code, message, span=None, path="n"):
        raise MathParseError(
            code,
            message,
            source=self.source,
            span=span if span is not None else self.peek().span,
            path=path,
            source_path=self.source_path,
            step=self.step,
        )

    def lex(self):
        tokens = []
        i = 0
        aliases = {
            "−": "-",
            "–": "-",
            "×": "*",
            "÷": "/",
            "≤": "<=",
            "≥": ">=",
            "≠": "!=",
            "≔": ":=",
            "（": "(",
            "）": ")",
            "，": ",",
        }
        while i < len(self.source):
            c, start = self.source[i], i
            if c.isspace():
                i += 1
                continue
            if c in SUPER_CHARS and not self.legacy:
                while i < len(self.source) and self.source[i] in SUPER_CHARS:
                    i += 1
                superscript = self.source[start:i].translate(SUPERSCRIPTS)
                if not re.fullmatch(r"[+-]?\d+", superscript):
                    self.fail("unsupported_power", "无效上标指数", (start, i))
                tokens.append(_Token("^", (start, i), True))
                if superscript[0] in "+-":
                    tokens.append(_Token(superscript[0], (start, start + 1)))
                    tokens.append(_Token(superscript[1:], (start + 1, i)))
                else:
                    tokens.append(_Token(superscript, (start, i)))
                continue
            match = NAME.match(self.source, i)
            if match:
                text, i = match.group(), match.end()
            elif c in "0123456789":
                i += 1
                while i < len(self.source) and self.source[i] in "0123456789":
                    i += 1
                text = self.source[start:i]
            elif c == "\\" and not self.legacy:
                match = re.match(r"\\[A-Za-z]+", self.source[i:])
                if not match or match.group() not in {r"\frac", r"\sqrt"}:
                    self.fail(
                        "unsupported_syntax",
                        "不支持的 LaTeX 命令",
                        (start, min(start + 12, len(self.source))),
                    )
                text = match.group()
                i += len(text)
            elif self.source[i : i + 2] in {"**", ">=", "<=", "!=", ":="}:
                text = self.source[i : i + 2]
                i += 2
                if text == "**":
                    text = "^"
            elif c in "+-*/^()=<>" or (not self.legacy and c in "{},√±∵∴"):
                text, i = c, i + 1
            elif not self.legacy and c in aliases:
                text, i = aliases[c], i + 1
            else:
                self.fail("unsupported_syntax", "不支持的数学字符", (i, i + 1))
            token = _Token(text, (start, i))
            if (
                not self.legacy
                and tokens
                and tokens[-1].text.isascii()
                and tokens[-1].text.isdigit()
                and self.source[slice(*tokens[-1].span)].isascii()
                and not (len(tokens) >= 2 and tokens[-2].text == "^")
                and not (
                    len(tokens) >= 3
                    and tokens[-2].text in {"+", "-"}
                    and tokens[-3].text == "^"
                )
                and (NAME.fullmatch(text) or text in {"(", "√", r"\sqrt", r"\frac"})
            ):
                tokens.append(_Token("*", (start, start), True))
            tokens.append(token)
        return tokens + [_Token("EOF", (len(self.source), len(self.source)))]

    def peek(self):
        return self.tokens[self.i]

    def take(self, expected=None):
        token = self.peek()
        if token.text == "EOF" or (expected is not None and token.text != expected):
            self.fail("invalid_syntax", f"期待 {expected or '数学表达式'}", token.span)
        self.i += 1
        return token

    def node(self, op, span, children=(), text=None, token=None):
        self.count += 1
        if self.count > 256:
            self.fail("expression_too_large", "节点数超过 256", span)
        return MathNode(
            op,
            span,
            tuple(children),
            text,
            token.span if token else None,
            synthetic=token.synthetic if token else False,
        )

    def group(self, opening, allow_pm):
        end = ")" if opening.text == "(" else "}"
        inner = self.expr(0, allow_pm=allow_pm)
        closing = self.take(end)
        return self.node(
            "group", (opening.span[0], closing.span[1]), (inner,), token=opening
        )

    def expr(self, minimum=0, *, allow_pm=False):
        self.depth += 1
        if self.depth > 32:
            self.fail("expression_too_deep", "嵌套深度超过 32")
        token = self.take()
        t = token.text
        if t in {"+", "-"} or (t == "±" and allow_pm):
            child = self.expr(30, allow_pm=allow_pm)
            left = self.node(
                {"+": "pos", "-": "neg", "±": "pm"}[t],
                (token.span[0], child.span[1]),
                (child,),
                token=token,
            )
        elif t == "(":
            left = self.group(token, allow_pm)
        elif t in {"sqrt", "√", r"\sqrt"}:
            if self.legacy:
                self.fail("unsupported_syntax", "当前能力只接受有理式", token.span)
            if t == "sqrt":
                child = self.group(self.take("("), allow_pm)
            elif t == r"\sqrt":
                child = self.group(self.take("{"), allow_pm)
            elif self.peek().text == "(":
                child = self.group(self.take("("), allow_pm)
            else:
                atom = self.peek()
                if not (
                    NAME.fullmatch(atom.text)
                    or atom.text.isascii()
                    and atom.text.isdigit()
                ) or atom.text in {"EOF", "sqrt"}:
                    self.fail(
                        "invalid_radical", "根号后需要数字、标识符或括号", atom.span
                    )
                child = self.expr(31, allow_pm=False)
            left = self.node(
                "sqrt", (token.span[0], child.span[1]), (child,), token=token
            )
        elif t == r"\frac":
            a = self.group(self.take("{"), allow_pm)
            b = self.group(self.take("{"), allow_pm)
            left = self.node("div", (token.span[0], b.span[1]), (a, b), token=token)
        elif t.isascii() and t.isdigit():
            if len(t) > 10 or int(t) > 10**9:
                self.fail("unsupported_number", "整数绝对值不得超过 10^9", token.span)
            left = self.node("integer", token.span, text=str(int(t)))
        elif NAME.fullmatch(t):
            if self.peek().text == "(":
                self.fail(
                    "unknown_function",
                    "只允许一元 sqrt；变量乘法需要显式 *",
                    token.span,
                )
            if not isinstance(self.symbols.get(t), sp.Symbol):
                self.fail("unknown_symbol", f"未知标量 {t}", token.span)
            left = self.node("symbol", token.span, text=t)
        else:
            self.fail("invalid_syntax", "期待标量表达式", token.span)
        while (
            self.peek().text in PRECEDENCE and PRECEDENCE[self.peek().text] >= minimum
        ):
            operator = self.take()
            if operator.text == "±" and not allow_pm:
                self.fail("unsupported_branch", "± 只允许在分支等式右侧", operator.span)
            priority = PRECEDENCE[operator.text]
            right = self.expr(
                priority if operator.text == "^" else priority + 1, allow_pm=allow_pm
            )
            left = self.node(
                BINARY[operator.text],
                (left.span[0], right.span[1]),
                (left, right),
                token=operator,
            )
        self.depth -= 1
        return left

    def relation_or_expression(self, *, relation_required=False, branches=False):
        # Parenthesized whole relations occur in canonical ProblemIR strings.
        if self.peek().text == "(" and self._whole_relation_group():
            opening = self.take()
            self.depth += 1
            if self.depth > 32:
                self.fail("expression_too_deep", "嵌套深度超过 32")
            inner = self.relation_or_expression(
                relation_required=relation_required, branches=branches
            )
            closing = self.take(")")
            self.depth -= 1
            return self.node(
                "group", (opening.span[0], closing.span[1]), (inner,), token=opening
            )
        left = self.expr()
        if self.peek().text not in RELATIONS:
            if relation_required:
                self.fail("invalid_condition", "需要单个等式或比较关系")
            return left
        operator = self.take()
        right = self.expr(allow_pm=branches and operator.text == "=")
        return self.node(
            operator.text, (left.span[0], right.span[1]), (left, right), token=operator
        )

    def _whole_relation_group(self):
        depth = 0
        relation = False
        for token in self.tokens[self.i :]:
            if token.text == "(":
                depth += 1
            elif token.text == ")":
                depth -= 1
                if depth == 0:
                    return relation
            elif token.text in RELATIONS:
                relation = True
        return False

    def finish(self, tree):
        if self.peek().text != "EOF":
            self.fail(
                "invalid_syntax", "只接受单个表达式或关系，不能隐式乘法或串联关系"
            )
        tree = _paths(tree)
        self.check(tree)
        pm = [n for n in tree.walk() if n.op == "pm"]
        if pm:
            if len(pm) != 1 or _ungroup(tree).op != "=":
                self.fail(
                    "unsupported_branch",
                    "每个分支等式只允许一个 ±",
                    pm[0].span,
                    pm[0].path,
                )
            ast = _paths(
                MathNode(
                    "branches",
                    tree.span,
                    tuple(
                        replace(_canonical(tree, sign), branch_id=label)
                        for sign, label in (("+", "positive"), ("-", "negative"))
                    ),
                )
            )
            self.check(ast)
        else:
            ast = _paths(_canonical(tree))
        obligations = []
        for n in ast.walk():
            if n.op == "sqrt":
                obligations.append(
                    DomainObligation(">=", n.children[0], n.path, n.span)
                )
            elif n.op == "div":
                obligations.append(
                    DomainObligation("!=", n.children[1], n.path, n.span)
                )
            elif n.op == "pow" and _integer(n.children[1]) < 0:
                obligations.append(
                    DomainObligation("!=", n.children[0], n.path, n.span)
                )
        normalized, mapping = _render(tree)
        return ParsedMath(
            self.source,
            normalized,
            mapping,
            tree,
            ast,
            tuple(obligations),
            self.source_path,
            self.step,
        )

    def check(self, tree):
        if sum(1 for _ in tree.walk()) > 256:
            self.fail("expression_too_large", "分支展开后节点数超过 256", tree.span)

        def visit(node, depth=0):
            if depth > 32:
                self.fail(
                    "expression_too_deep", "结构深度超过 32", node.span, node.path
                )
            checked_children = [visit(c, depth + 1) for c in node.children]
            sizes = [size for size, _ in checked_children]
            constants = [value for _, value in checked_children]
            op = node.op
            size = max(sizes, default=1)
            if op == "pow":
                exponent = _integer(node.children[1])
                if exponent is None or abs(exponent) > 12:
                    self.fail(
                        "unsupported_power",
                        "指数必须是绝对值不超过 12 的整数字面量",
                        node.children[1].span,
                        node.children[1].path,
                    )
                if any(n.op == "pow" for n in node.children[0].walk()):
                    self.fail(
                        "expression_too_large", "首轮不接受嵌套幂", node.span, node.path
                    )
                if (
                    sum(
                        1
                        for n in node.children[0].walk()
                        if n.children and n.op != "group"
                    )
                    > 24
                ):
                    self.fail(
                        "expression_too_large", "幂的底数结构过大", node.span, node.path
                    )
                if constants[0] == 0 and exponent < 0:
                    self.fail(
                        "undefined_expression", "零不能取负幂", node.span, node.path
                    )
                size = sizes[0] ** abs(exponent)
            elif op in {"add", "sub", "pm", "branches", "premise", "conclusion"}:
                size = sum(sizes)
            elif op in {"mul", "div"}:
                size = sizes[0] * sizes[1]
            if size > 128:
                self.fail("proof_limit", "潜在展开规模超过 128", node.span, node.path)
            if op == "div" and constants[1] == 0:
                self.fail("undefined_expression", "分母不能是零", node.span, node.path)
            if op == "sqrt":
                literal = constants[0]
                if literal is not None and literal < 0:
                    self.fail(
                        "undefined_expression",
                        "实数根式不能取负常量",
                        node.span,
                        node.path,
                    )
            return size, _constant_value(node, constants)

        visit(tree)


def _parse(source, symbols, *, relation=False, legacy=False):
    parser = _Parser(source, symbols, legacy=legacy)
    tree = (
        parser.relation_or_expression(relation_required=True)
        if relation
        else parser.expr()
    )
    return parser.finish(tree)


def parse_math_expression(source: str, symbols: Mapping[str, sp.Symbol]) -> ParsedMath:
    return _parse(source, symbols)


def parse_math_relation(source: str, symbols: Mapping[str, sp.Symbol]) -> ParsedMath:
    return _parse(source, symbols, relation=True)


def parse_math_steps(
    steps: Sequence[dict[str, str]], symbols: Mapping[str, sp.Symbol]
) -> tuple[ParsedMath, ...]:
    """Parse up to 12 math rows. Definitions do not extend ``symbols``.

    Rows use the existing {"math": ...} envelope; source_path is a JSON pointer
    relative to that steps array. ∵/∴ pairs link adjacent rows syntactically only.
    """
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= 12:
        raise MathParseError(
            "invalid_steps",
            "需要 1–12 个数学步骤",
            source="",
            span=(0, 0),
            source_path="/",
        )
    results = []
    pending = None
    for i, row in enumerate(steps):
        if not isinstance(row, dict) or set(row) != {"math"}:
            raise MathParseError(
                "invalid_step",
                "每行只能包含 math",
                source="",
                span=(0, 0),
                step=i,
                source_path=f"/{i}",
            )
        parser = _Parser(row["math"], symbols, step=i, source_path=f"/{i}/math")
        first = parser.peek()
        if first.text in {"∵", "∴"}:
            marker = parser.take()
            relations = [parser.relation_or_expression(relation_required=True)]
            while marker.text == "∵" and parser.peek().text == ",":
                parser.take()
                relations.append(parser.relation_or_expression(relation_required=True))
                if len(relations) > 8:
                    parser.fail("proof_limit", "每行最多 8 个前提")
            tree = parser.node(
                "premise" if marker.text == "∵" else "conclusion",
                (marker.span[0], relations[-1].span[1]),
                relations,
                token=marker,
            )
        elif len(parser.tokens) > 2 and parser.tokens[1].text == ":=":
            name, marker = parser.take(), parser.take()
            if not NAME.fullmatch(name.text) or name.text == "sqrt":
                parser.fail("invalid_definition", "定义左侧必须是标识符", name.span)
            target = parser.node("binding", name.span, text=name.text)
            expression = parser.expr()
            tree = parser.node(
                "definition",
                (name.span[0], expression.span[1]),
                (target, expression),
                token=marker,
            )
        else:
            tree = parser.relation_or_expression(branches=True)
        parsed = parser.finish(tree)
        if parsed.ast.op == "conclusion":
            if pending is None:
                parser.fail("unpaired_logic", "∴ 前必须紧邻 ∵ 行", first.span)
            results[-1] = replace(results[-1], related_step=i)
            parsed = replace(parsed, related_step=pending)
            pending = None
        elif pending is not None:
            parser.fail("unpaired_logic", "∵ 后必须紧邻 ∴ 行", first.span)
        elif parsed.ast.op == "premise":
            pending = i
        results.append(parsed)
    if pending is not None:
        row = results[pending]
        raise MathParseError(
            "unpaired_logic",
            "∵ 后缺少 ∴ 行",
            source=row.source,
            span=row.tree.span,
            source_path=row.source_path,
            step=pending,
        )
    return tuple(results)
