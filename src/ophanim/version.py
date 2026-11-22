"""Version identifiers.

ENV_VERSION is part of the reproducibility contract: identical
(seed, config, ENV_VERSION, action sequence) must reproduce identical records,
transitions and rewards. Bump it whenever generation or evaluation logic changes.
"""

ENV_VERSION = "0.3.0"  # 0.3.0: refunds (D03), allocation_mode (D09-D11), guaranteed split (D02), foreign FX boundary (D05)
SCHEMA_VERSION = "1.0"
CONFIG_VERSION = "1.0"
