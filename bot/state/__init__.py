"""Game state: the dataclass the bot acts on, kept current from the wire."""
from bot.state.game_state import GameState, Scene
from bot.state.stream_reader import StreamReader

# LiveState defers its heavy tools/ capture imports to .start(), so naming it
# here stays cheap.
from bot.state.live import CaptureUnavailable, LiveState

__all__ = ["GameState", "Scene", "StreamReader", "LiveState", "CaptureUnavailable"]
