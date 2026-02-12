import asyncio
from enum import Enum

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class ToolCall(Enum):
    FIND_PATIENT = "find_patient"
    CREATE_APPOINTMENT = "create_appointment"
    CANCEL_APPOINTMENT = "cancel_appointment"


FILLER_PHRASES: dict[ToolCall, str] = {
    ToolCall.FIND_PATIENT: "One moment, let me look up your record.",
    ToolCall.CREATE_APPOINTMENT: "Let me book that for you, just a moment.",
    ToolCall.CANCEL_APPOINTMENT: "One moment while I cancel that for you.",
}

DEFAULT_FILLER: str = "One moment please."

# Seconds to wait before speaking the filler.
# Typical fast tool calls resolve in < 1s; Playwright can take 3-5s.
DEFAULT_DELAY_SECONDS: float = 1.5


class ToolCallFillerProcessor(FrameProcessor):
    """Speaks a filler phrase only when a tool call exceeds a time threshold.

    Place this processor between the LLM and TTS in the pipeline:

        pipeline = Pipeline([
            ...,
            llm,
            ToolCallFillerProcessor(),
            tts,
            ...,
        ])
    """

    def __init__(
        self,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        phrases: dict[ToolCall, str] | None = None,
        default_phrase: str = DEFAULT_FILLER,
    ) -> None:
        super().__init__()  # pyright: ignore[reportUnknownMemberType]
        self._delay = delay_seconds
        self._phrases = phrases or FILLER_PHRASES
        self._default = default_phrase
        # Pending filler tasks keyed by tool_call_id
        self._pending: dict[str, asyncio.Task[None]] = {}

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, FunctionCallInProgressFrame):
            await self.push_frame(frame, direction)
            # Schedule a filler after the delay
            try:
                text = self._phrases[ToolCall(frame.function_name)]
            except (ValueError, KeyError):
                text = self._default
            task = asyncio.create_task(self._delayed_filler(frame.tool_call_id, text))
            self._pending[frame.tool_call_id] = task
            return

        if isinstance(frame, FunctionCallResultFrame):
            # Tool finished — cancel the filler if it hasn't spoken yet
            pending_task = self._pending.pop(frame.tool_call_id, None)
            if pending_task is not None and not pending_task.done():
                pending_task.cancel()
                logger.debug(
                    "Filler cancelled — tool '{}' resolved before {}s threshold",
                    frame.function_name,
                    self._delay,
                )
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    async def _delayed_filler(self, tool_call_id: str, text: str) -> None:
        """Wait, then inject the filler phrase if not cancelled."""
        try:
            await asyncio.sleep(self._delay)
            logger.info("Speaking filler for slow tool call {}", tool_call_id)
            await self.push_frame(TTSSpeakFrame(text=text), FrameDirection.DOWNSTREAM)
        except asyncio.CancelledError:
            pass  # Tool resolved in time — no filler needed
        finally:
            self._pending.pop(tool_call_id, None)
