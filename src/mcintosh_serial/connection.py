"""One-call setup: open the port for a model and get a started client."""

from mcintosh_serial.client import Client, client_for
from mcintosh_serial.profiles import get_profile
from mcintosh_serial.transport import open_serial


async def connect(url: str, model: str, *, baudrate: int | None = None) -> Client:
    """Open ``url`` for a model such as ``"mx119"`` and return a started client.

    The baud rate defaults to the model's; pass ``baudrate`` if the unit's menu
    was set to something else. Raises ``ValueError`` for an unknown model.
    """
    profile = get_profile(model)
    client = client_for(await open_serial(url, baudrate or profile.baudrate), profile)
    try:
        await client.start()
    except BaseException:
        await client.stop()
        raise
    return client
