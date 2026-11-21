"""Deterministic random numbers that are identical on every Python version.

Why not the standard ``random`` module?
    The Python documentation guarantees only that ``random.random()`` keeps
    producing the same sequence for the same seed across versions. Helpers such
    as ``randrange``, ``choice``, ``shuffle`` and ``sample`` are explicitly
    allowed to change between releases. OPHANIM promises that the same seed
    reproduces the same episode on Python 3.11 and 3.14, so we cannot rely on them.

What we use instead
    SHA-256 in counter mode. Block ``i`` of a stream is
    ``SHA256(key || i as 8 big-endian bytes)``. SHA-256 is standardised
    (FIPS 180-4), so the output depends only on the key and the counter, never
    on the interpreter. Every helper below (``randbelow``, ``shuffle``, ...) is
    implemented here with integer arithmetic only - no floats anywhere.

Named sub-streams
    ``rng.child("fx")`` derives an independent stream from the parent key and a
    name. Generation stages use separate children, so adding a new red-herring
    type cannot change the FX rates or the invoice amounts of an existing seed.

Closed evaluation secret
    ``from_seed(seed, secret=...)`` keys the root stream with
    HMAC-SHA256(secret, seed). The generator is open source; without the secret,
    an agent that guesses a small hidden seed could regenerate the episode and
    read the answers. With a secret held only by the evaluator, that attack is
    infeasible. Open train/dev episodes use no secret.

Golden values for this module are pinned in tests/unit/test_rng.py and the test
suite is run on both Python 3.11 and 3.14.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import MutableSequence, Sequence, TypeVar

T = TypeVar("T")

_NAMESPACE = "ophanim/rng/v1"


class DeterministicRng:
    """A small, fully deterministic random number generator (see module docstring)."""

    __slots__ = ("_key", "_counter", "_pool", "_pool_bits")

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("DeterministicRng key must be exactly 32 bytes")
        self._key = key
        self._counter = 0
        self._pool = 0
        self._pool_bits = 0

    # ------------------------------------------------------------------ creation
    @classmethod
    def from_seed(cls, seed: int, *, secret: bytes | None = None) -> "DeterministicRng":
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an int")
        material = f"{_NAMESPACE}|seed={seed}".encode("utf-8")
        if secret:
            key = hmac.new(secret, material, hashlib.sha256).digest()
        else:
            key = hashlib.sha256(material).digest()
        return cls(key)

    def child(self, name: str) -> "DeterministicRng":
        """Independent sub-stream identified by ``name`` (does not consume parent state)."""
        return DeterministicRng(hashlib.sha256(self._key + b"/child/" + name.encode("utf-8")).digest())

    def fingerprint(self, label: str) -> str:
        """Stable hex digest derived from the key (used for public episode ids)."""
        return hashlib.sha256(self._key + b"/fingerprint/" + label.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ core bits
    def _next_block(self) -> int:
        block = hashlib.sha256(self._key + self._counter.to_bytes(8, "big")).digest()
        self._counter += 1
        return int.from_bytes(block, "big")

    def getrandbits(self, k: int) -> int:
        if k < 0:
            raise ValueError("k must be non-negative")
        if k == 0:
            return 0
        while self._pool_bits < k:
            self._pool = (self._pool << 256) | self._next_block()
            self._pool_bits += 256
        self._pool_bits -= k
        value = self._pool >> self._pool_bits
        self._pool &= (1 << self._pool_bits) - 1
        return value

    # ------------------------------------------------------------------ helpers
    def randbelow(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (unbiased)."""
        if n <= 0:
            raise ValueError("n must be positive")
        bits = n.bit_length()
        while True:
            r = self.getrandbits(bits)
            if r < n:
                return r

    def randint(self, a: int, b: int) -> int:
        """Uniform integer in [a, b] (both inclusive)."""
        if b < a:
            raise ValueError("empty range")
        return a + self.randbelow(b - a + 1)

    def choice(self, seq: Sequence[T]) -> T:
        if not seq:
            raise ValueError("cannot choose from an empty sequence")
        return seq[self.randbelow(len(seq))]

    def chance(self, numerator: int, denominator: int) -> bool:
        """True with probability numerator/denominator (integers only)."""
        if denominator <= 0 or numerator < 0:
            raise ValueError("invalid probability")
        return self.randbelow(denominator) < numerator

    def weighted_choice(self, items: Sequence[T], weights: Sequence[int]) -> T:
        if len(items) != len(weights) or not items:
            raise ValueError("items and weights must be non-empty and equally long")
        if any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative")
        total = sum(weights)
        if total <= 0:
            raise ValueError("at least one weight must be positive")
        r = self.randbelow(total)
        for item, w in zip(items, weights):
            if r < w:
                return item
            r -= w
        raise AssertionError("unreachable")

    def shuffle(self, items: MutableSequence[T]) -> None:
        """In-place Fisher-Yates shuffle."""
        for i in range(len(items) - 1, 0, -1):
            j = self.randbelow(i + 1)
            items[i], items[j] = items[j], items[i]

    def sample(self, seq: Sequence[T], k: int) -> list[T]:
        """k distinct elements, in selection order."""
        if k < 0 or k > len(seq):
            raise ValueError("sample size out of range")
        pool = list(seq)
        out: list[T] = []
        for _ in range(k):
            out.append(pool.pop(self.randbelow(len(pool))))
        return out

    def token(self, length: int, alphabet: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789") -> str:
        """Random identifier-safe string (no 0/O/1/I to avoid confusion)."""
        return "".join(alphabet[self.randbelow(len(alphabet))] for _ in range(length))
