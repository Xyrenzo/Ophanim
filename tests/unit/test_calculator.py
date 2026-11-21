import pytest

from ophanim.env.calculator import CalculatorError, evaluate


@pytest.mark.parametrize("expr,expected", [
    ("1+2*3", "7"),
    ("(1+2)*3", "9"),
    ("0.1+0.2", "0.3"),           # exact decimal, no binary float error
    ("10/4", "2.5"),
    ("-3+5", "2"),
    ("--3", "3"),
    ("2 * (3.5 - 1.25)", "4.5"),
    ("1250.00 * 1.083215", "1354.01875"),
    (".5 + .25", "0.75"),
    ("100 - 100", "0"),
])
def test_arithmetic(expr, expected):
    assert evaluate(expr) == expected


def test_division_keeps_34_significant_digits():
    assert evaluate("1/3") == "0." + "3" * 34


@pytest.mark.parametrize("expr", [
    "__import__('os')", "open('truth.json')", "1e5", "2**3", "abs(1)", "a+1", "1;2", "", "   ",
    "1+", "(1", "1)", "1 2", "１+1", "١+1", "1_000", "0x10", "[1]", "'1'", "1 % 2", "1 // 2", "True",
])
def test_rejects_anything_but_arithmetic(expr):
    with pytest.raises(CalculatorError):
        evaluate(expr)


def test_bounded_errors():
    with pytest.raises(CalculatorError) as e:
        evaluate("1/0")
    assert e.value.code == "division_by_zero"
    with pytest.raises(CalculatorError) as e:
        evaluate("1+" * 200 + "1")
    assert e.value.code == "expression_too_long"
    with pytest.raises(CalculatorError) as e:
        evaluate("(" * 40 + "1" + ")" * 40)
    assert e.value.code == "expression_too_complex"
    with pytest.raises(CalculatorError) as e:
        evaluate("1" * 31)
    assert e.value.code == "number_too_long"
    big = "*".join(["9" * 30] * 4)
    with pytest.raises(CalculatorError) as e:
        evaluate(big)
    assert e.value.code == "result_out_of_range"


@pytest.mark.parametrize("value", [None, 5, 1.5, ["1"], {"x": 1}])
def test_non_string_input(value):
    with pytest.raises(CalculatorError):
        evaluate(value)
