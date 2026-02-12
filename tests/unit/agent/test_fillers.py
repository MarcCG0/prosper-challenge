"""Unit tests for the ToolCallFillerProcessor."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import (
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from prosper.agent.fillers import (
    DEFAULT_FILLER,
    FILLER_PHRASES,
    ToolCall,
    ToolCallFillerProcessor,
)


def _in_progress(
    function_name: str = ToolCall.FIND_PATIENT.value, tool_call_id: str = "call-1"
) -> FunctionCallInProgressFrame:
    return FunctionCallInProgressFrame(
        function_name=function_name,
        tool_call_id=tool_call_id,
        arguments={},
    )


def _result(
    function_name: str = ToolCall.FIND_PATIENT.value, tool_call_id: str = "call-1"
) -> FunctionCallResultFrame:
    return FunctionCallResultFrame(
        function_name=function_name,
        tool_call_id=tool_call_id,
        arguments={},
        result={"found": True},
    )


class TestFillerPhrases:
    def test_all_tools_have_phrases(self) -> None:
        assert set(FILLER_PHRASES.keys()) == set(ToolCall)


class TestProcessFrame:
    @pytest.mark.asyncio
    async def test_filler_speaks_when_tool_is_slow(self) -> None:
        proc = ToolCallFillerProcessor(delay_seconds=0.05)
        proc.push_frame = AsyncMock()

        await proc.process_frame(_in_progress(), FrameDirection.DOWNSTREAM)
        # Wait long enough for the filler to fire
        await asyncio.sleep(0.1)

        # Should have pushed: the original in-progress frame + a TTSSpeakFrame
        pushed_frames = [c.args[0] for c in proc.push_frame.call_args_list]
        assert any(isinstance(f, FunctionCallInProgressFrame) for f in pushed_frames)
        tts_frames = [f for f in pushed_frames if isinstance(f, TTSSpeakFrame)]
        assert len(tts_frames) == 1
        assert tts_frames[0].text == FILLER_PHRASES[ToolCall.FIND_PATIENT]

    @pytest.mark.asyncio
    async def test_filler_cancelled_when_tool_resolves_fast(self) -> None:
        proc = ToolCallFillerProcessor(delay_seconds=10)
        proc.push_frame = AsyncMock()

        await proc.process_frame(_in_progress(), FrameDirection.DOWNSTREAM)
        # Tool resolves immediately — filler should be cancelled
        await proc.process_frame(_result(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        pushed_frames = [c.args[0] for c in proc.push_frame.call_args_list]
        assert not any(isinstance(f, TTSSpeakFrame) for f in pushed_frames)

    @pytest.mark.asyncio
    async def test_uses_default_filler_for_unknown_tool(self) -> None:
        proc = ToolCallFillerProcessor(delay_seconds=0.05)
        proc.push_frame = AsyncMock()

        await proc.process_frame(
            _in_progress(function_name="unknown_tool"), FrameDirection.DOWNSTREAM
        )
        await asyncio.sleep(0.1)

        pushed_frames = [c.args[0] for c in proc.push_frame.call_args_list]
        tts_frames = [f for f in pushed_frames if isinstance(f, TTSSpeakFrame)]
        assert len(tts_frames) == 1
        assert tts_frames[0].text == DEFAULT_FILLER

    @pytest.mark.asyncio
    async def test_passes_through_non_tool_frames(self) -> None:
        proc = ToolCallFillerProcessor()
        proc.push_frame = AsyncMock()

        frame = TTSSpeakFrame(text="hello")
        await proc.process_frame(frame, FrameDirection.DOWNSTREAM)

        proc.push_frame.assert_called_once_with(frame, FrameDirection.DOWNSTREAM)

    @pytest.mark.asyncio
    async def test_result_frame_passed_through(self) -> None:
        proc = ToolCallFillerProcessor(delay_seconds=10)
        proc.push_frame = AsyncMock()

        result = _result()
        await proc.process_frame(result, FrameDirection.DOWNSTREAM)

        pushed_frames = [c.args[0] for c in proc.push_frame.call_args_list]
        assert result in pushed_frames
