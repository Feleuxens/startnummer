"""Sport registration and the discriminated event union."""

from typing import Annotated

from pydantic import Field

from startnummer.core.sports.athletics import AthleticsEvent
from startnummer.core.sports.base import get
from startnummer.core.sports.handball import HandballEvent

# Discriminated on sport; importing the event models above also registers the modules.
Event = Annotated[AthleticsEvent | HandballEvent, Field(discriminator="sport")]

__all__ = ["Event", "get"]
