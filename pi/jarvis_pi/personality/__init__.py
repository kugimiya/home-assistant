"""Assistant personality: identity, session affect, slow trust drift."""

from jarvis_pi.personality.affect import Affect, classify
from jarvis_pi.personality.prompt import IDENTITY_INSTRUCTIONS
from jarvis_pi.personality.state import note_user_affect, on_session_end
from jarvis_pi.personality.style import render_style_card

__all__ = [
    "Affect",
    "IDENTITY_INSTRUCTIONS",
    "classify",
    "note_user_affect",
    "on_session_end",
    "render_style_card",
]
