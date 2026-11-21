"""Cross-version reproducibility of the RNG.

The golden values below were produced once and must hold on every supported
Python version (the suite is run on 3.11 and 3.14). If any of them changes, every
published seed would produce a different episode.
"""

from ophanim.rng import DeterministicRng as R


def test_golden_values_are_version_independent():
    r = R.from_seed(42)
    assert r.getrandbits(64) == 776096487018440394
    assert [r.randbelow(1000) for _ in range(5)] == [171, 42, 457, 781, 378]
    r = R.from_seed(42)
    xs = list(range(10))
    r.shuffle(xs)
    assert xs == [7, 2, 1, 9, 8, 4, 6, 3, 5, 0]
    assert r.token(8) == "PPFYFV4V"
    assert R.from_seed(42).child("fx").getrandbits(32) == 1061132103
    assert R.from_seed(42, secret=b"jury").getrandbits(64) == 14596528975605107314
    assert R.from_seed(42).fingerprint("episode")[:16] == "9ff846f6d49d4327"


def test_same_seed_same_stream_different_seed_different_stream():
    assert [R.from_seed(1).randbelow(10**9) for _ in range(3)] == [R.from_seed(1).randbelow(10**9) for _ in range(3)]
    assert R.from_seed(1).getrandbits(128) != R.from_seed(2).getrandbits(128)


def test_secret_changes_the_stream():
    assert R.from_seed(5).getrandbits(128) != R.from_seed(5, secret=b"x").getrandbits(128)
    assert R.from_seed(5, secret=b"x").getrandbits(128) == R.from_seed(5, secret=b"x").getrandbits(128)


def test_children_are_independent_of_parent_consumption():
    a = R.from_seed(9)
    child_before = a.child("names").getrandbits(64)
    a.getrandbits(4096)
    assert a.child("names").getrandbits(64) == child_before
    assert a.child("names").getrandbits(64) != a.child("ids").getrandbits(64)


def test_helpers_respect_bounds():
    r = R.from_seed(3)
    for n in (1, 2, 3, 7, 1000, 2**40 + 3):
        for _ in range(50):
            assert 0 <= r.randbelow(n) < n
    for _ in range(200):
        assert 5 <= r.randint(5, 9) <= 9
    s = r.sample(list(range(20)), 10)
    assert len(set(s)) == 10
    assert r.weighted_choice(["a", "b"], [0, 5]) == "b"
    assert r.chance(0, 10) is False and r.chance(10, 10) is True


def test_rejects_float_or_bool_seed():
    import pytest

    for bad in (1.0, True, "3"):
        with pytest.raises(TypeError):
            R.from_seed(bad)  # type: ignore[arg-type]
