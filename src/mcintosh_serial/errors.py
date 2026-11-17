"""Exceptions raised by the client."""


class McIntoshError(Exception):
    """Base class for all library errors."""


class McIntoshConnectionError(McIntoshError):
    """The transport closed or could not be used."""


class McIntoshTimeoutError(McIntoshError):
    """The unit did not send the expected reply in time."""

    def __init__(self, command: str) -> None:
        super().__init__(f"no reply to {command}")
        self.command = command


class McIntoshCommandError(McIntoshError):
    """The unit rejected a command; ``code`` is its error code or text."""

    def __init__(self, code: str, command: str) -> None:
        super().__init__(f"{command.strip()} rejected by the unit (error: {code})")
        self.code = code
        self.command = command
