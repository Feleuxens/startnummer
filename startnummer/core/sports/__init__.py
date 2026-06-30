"""Sport registry assembly. Importing a sport module registers it.

Adding a sport: create the module (register() inside it), import its event model
here, and add it to the Event union. That union line and the Sport enum are the
only shared edits; everything else is the new file.
"""

from typing import Annotated

from pydantic import Field

from startnummer.core.sports.athletics import AthleticsEvent
from startnummer.core.sports.base import get
from startnummer.core.sports.handball import HandballEvent

# Discriminated on sport; importing the event models above also registers the modules.
Event = Annotated[AthleticsEvent | HandballEvent, Field(discriminator="sport")]

__all__ = ["Event", "get"]
