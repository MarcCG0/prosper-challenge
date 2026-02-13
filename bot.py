from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi import RTVIObserver, RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport  # type: ignore[import-untyped]
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from prosper.agent.fillers import ToolCallFillerProcessor
from prosper.agent.prompts import build_system_prompt
from prosper.agent.tools import get_tools_schema, register_tools
from prosper.config import AppConfig
from prosper.ehr.factory import build_ehr_service

logger.info("All components loaded successfully!")


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    logger.info("Starting Prosper Health scheduling agent")

    config = AppConfig()
    ehr_service = build_ehr_service(config)

    stt = ElevenLabsRealtimeSTTService(api_key=config.elevenlabs.api_key)
    tts = ElevenLabsTTSService(
        api_key=config.elevenlabs.api_key,
        voice_id=config.elevenlabs.voice_id,
    )

    llm = OpenAILLMService(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
    )

    register_tools(llm, ehr_service, clinic_timezone=config.clinic_timezone)

    system_prompt = build_system_prompt(config.clinic_timezone)
    initial_messages = [{"role": "system", "content": system_prompt}]
    tools = get_tools_schema()
    context = LLMContext(messages=list(initial_messages), tools=tools)  # type: ignore[arg-type]

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
            ),
        ),
    )

    rtvi = RTVIProcessor()

    filler = ToolCallFillerProcessor()

    pipeline = Pipeline(
        [
            transport.input(),
            rtvi,
            stt,
            user_aggregator,
            llm,
            filler,  # Speaks contextual filler phrases during tool execution
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport: BaseTransport, client: object) -> None:  # type: ignore
        logger.info("Client connected")
        context.set_messages(list(initial_messages))  # type: ignore[arg-type]
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport: BaseTransport, client: object) -> None:  # type: ignore
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    try:
        await runner.run(task)
    finally:
        await ehr_service.close()


async def bot(runner_args: RunnerArguments) -> None:
    """Main bot entry point for the bot starter."""
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
        ),
    }

    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
