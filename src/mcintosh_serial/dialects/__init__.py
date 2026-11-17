"""Protocol dialects (one module per McIntosh command style)."""

from typing import TYPE_CHECKING

from mcintosh_serial.dialects.bang import BangDialect
from mcintosh_serial.dialects.simple import SimpleDialect
from mcintosh_serial.dialects.zoned import ZonedDialect

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from mcintosh_serial.dialects.base import Dialect

# name -> factory. Add a new dialect here once its module exists.
DIALECTS: Mapping[str, Callable[[], Dialect]] = {
    BangDialect.name: BangDialect,
    SimpleDialect.name: SimpleDialect,
    ZonedDialect.name: ZonedDialect,
}


def get_dialect(name: str) -> Dialect:
    """Create the dialect registered under ``name``."""
    try:
        return DIALECTS[name]()
    except KeyError:
        known = ", ".join(sorted(DIALECTS))
        message = f"unknown dialect {name!r} (known: {known})"
        raise ValueError(message) from None
