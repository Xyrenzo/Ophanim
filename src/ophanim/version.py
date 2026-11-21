"""Version identifiers.

ENV_VERSION is part of the reproducibility contract: identical
(seed, config, ENV_VERSION, action sequence) must reproduce identical records,
transitions and rewards. Bump it whenever generation or evaluation logic changes.
"""

ENV_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"
CONFIG_VERSION = "1.0"
