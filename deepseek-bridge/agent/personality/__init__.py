"""Assistant personality: identity, session affect, slow trust drift."""

from agent.personality.affect import Affect, classify
from agent.personality.prompt import IDENTITY_INSTRUCTIONS
from agent.personality.state import note_user_affect, on_session_end
from agent.personality.style import render_style_card

__all__ = [
    "Affect",
    "IDENTITY_INSTRUCTIONS",
    "classify",
    "note_user_affect",
    "on_session_end",
    "render_style_card",
]
