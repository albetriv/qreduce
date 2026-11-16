"""QReduce: combinatorial-domain reduction for mixed optimization problems."""

import logging

__version__ = "0.1.0"

# Library-style logging: add NullHandler so applications control destinations.
# See https://docs.python.org/3/howto/logging.html#configuring-logging-for-a-library
logging.getLogger(__name__).addHandler(logging.NullHandler())