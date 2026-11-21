"""Safe decimal calculator.

Grammar (nothing else is accepted - no names, calls, attributes, powers, strings):

    expr   := term (("+" | "-") term)*
    term   := factor (("*" | "/") factor)*
    factor := ("+" | "-") factor | NUMBER | "(" expr ")"
    NUMBER := digits ["." digits] | "." digits

Implemented with a hand-written tokenizer and recursive-descent parser; Python's
``eval``/``exec``/``ast`` are never used. Numbers are parsed from the source text
straight into ``decimal.Decimal`` (no binary floats). Limits bound CPU/memory.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext

MAX_LENGTH = 256
MAX_TOKENS = 128
MAX_DEPTH = 32
MAX_NUMBER_DIGITS = 30
MAX_RESULT_EXPONENT = 40

_CTX = Context(prec=34, rounding=ROUND_HALF_EVEN, Emax=999, Emin=-999,
               traps=[InvalidOperation, DivisionByZero, Overflow])
_TOKEN = re.compile(r"[ \t]*(?:([0-9]+(?:\.[0-9]+)?|\.[0-9]+)|([+\-*/()]))")  # ASCII only


class CalculatorError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    text = text.rstrip(" \t")
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise CalculatorError("invalid_expression")
        number, op = m.group(1), m.group(2)
        if number is not None:
            if len(number.replace(".", "")) > MAX_NUMBER_DIGITS:
                raise CalculatorError("number_too_long")
            tokens.append(("num", number))
        else:
            tokens.append(("op", op))
        pos = m.end()
        if len(tokens) > MAX_TOKENS:
            raise CalculatorError("expression_too_complex")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise CalculatorError("invalid_expression")
        self.i += 1
        return tok

    def expr(self) -> Decimal:
        value = self.term()
        while (tok := self.peek()) is not None and tok in (("op", "+"), ("op", "-")):
            self.take()
            rhs = self.term()
            value = value + rhs if tok[1] == "+" else value - rhs
        return value

    def term(self) -> Decimal:
        value = self.factor()
        while (tok := self.peek()) is not None and tok in (("op", "*"), ("op", "/")):
            self.take()
            rhs = self.factor()
            value = value * rhs if tok[1] == "*" else value / rhs
        return value

    def factor(self) -> Decimal:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalculatorError("expression_too_complex")
        try:
            kind, text = self.take()
            if kind == "num":
                return Decimal(text)
            if text == "-":
                return -self.factor()
            if text == "+":
                return +self.factor()
            if text == "(":
                value = self.expr()
                if self.take() != ("op", ")"):
                    raise CalculatorError("invalid_expression")
                return value
            raise CalculatorError("invalid_expression")
        finally:
            self.depth -= 1


def evaluate(expression: object) -> str:
    """Evaluate an arithmetic expression and return the exact decimal result as a string."""
    if not isinstance(expression, str):
        raise CalculatorError("invalid_expression")
    if len(expression) > MAX_LENGTH:
        raise CalculatorError("expression_too_long")
    tokens = _tokenize(expression)
    if not tokens:
        raise CalculatorError("invalid_expression")
    with localcontext(_CTX):
        try:
            parser = _Parser(tokens)
            value = parser.expr()
            if parser.peek() is not None:
                raise CalculatorError("invalid_expression")
            value = +value  # apply context precision
        except DivisionByZero:
            raise CalculatorError("division_by_zero") from None
        except (InvalidOperation, Overflow):
            raise CalculatorError("result_out_of_range") from None
        if value != 0 and abs(value.adjusted()) > MAX_RESULT_EXPONENT:
            raise CalculatorError("result_out_of_range")
        if value == 0:
            return "0"
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
