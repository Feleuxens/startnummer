"""Private caption-name preferences, separate from roster matching."""

from startnummer.app.contracts import CaptionNames
from startnummer.core.batch import Conflict
from startnummer.core.description import caption_name_key


def caption_preferences(store, owner_id, *, session=None):
    revision, document = store.runtime_settings(owner_id, session=session)
    return CaptionNames(revision=revision, overrides=document.get("caption_name_overrides", []))


def caption_overrides(store, owner_id, *, session=None, expected_revision=None):
    preferences = caption_preferences(store, owner_id, session=session)
    if expected_revision is not None and expected_revision != preferences.revision:
        raise Conflict("Caption name overrides changed; preview the changes again")
    names = {caption_name_key(rule.source_name): rule.caption_name for rule in preferences.overrides}
    return preferences.revision, names
