import json
import time
from typing import AsyncGenerator, List, Dict, Any, Optional
from app.modules.agent.schemas.chat import AgentState, StreamEventType, SessionType
from app.modules.agent.schemas.tools import ToolExecutionStatus
from app.modules.agent.state import AgentExecutionState
from app.modules.agent.llm.base import LLMProvider
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.security.audit import AgentAuditService
from app.modules.agent.prompts.user_prompt import USER_AGENT_SYSTEM_PROMPT
from app.modules.agent.prompts.admin_prompt import ADMIN_AGENT_SYSTEM_PROMPT
from app.core.logging import logger

MAX_AGENT_STEPS = 8
MAX_TOOL_CALLS = 12
MAX_EXECUTION_TIME_SECONDS = 35.0

class AgentOrchestrator:
    """
    Autonomous ReAct loop planner and executor.
    Manages multi-turn tool execution, state transitions, and real-time SSE stream events.
    """

    def __init__(
        self,
        llm: LLMProvider,
        registry: ToolRegistry,
        audit_service: AgentAuditService,
    ):
        self.llm = llm
        self.registry = registry
        self.audit = audit_service

    async def execute_turn_stream(
        self,
        session_id: str,
        user_id: str,
        user_role: str,
        session_type: SessionType,
        user_message: str,
        conversation_history: List[Dict[str, Any]],
        confirmation_token: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        state = AgentExecutionState(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            session_type=session_type,
        )

        # 1. State: RECEIVED
        yield {"event": StreamEventType.STATE.value, "data": {"state": AgentState.RECEIVED.value}}

        # 2. State: AUTHENTICATING & Tool Resolution
        state.transition(AgentState.AUTHENTICATING)
        yield {"event": StreamEventType.STATE.value, "data": {"state": AgentState.AUTHENTICATING.value}}

        system_prompt = ADMIN_AGENT_SYSTEM_PROMPT if session_type == SessionType.ADMIN else USER_AGENT_SYSTEM_PROMPT
        tools_for_role = self.registry.get_schemas_for_role(user_role)

        # 3. Assemble Messages Envelope
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        start_time = time.time()
        loop_count = 0
        final_answer = ""

        # 4. State: PLANNING & Autonomous ReAct Execution Loop
        while loop_count < MAX_AGENT_STEPS:
            loop_count += 1
            state.increment_step()

            if (time.time() - start_time) > MAX_EXECUTION_TIME_SECONDS:
                logger.warning(f"Agent turn timed out for session {session_id}")
                yield {"event": StreamEventType.ERROR.value, "data": {"error": "Execution time limit exceeded."}}
                break

            state.transition(AgentState.PLANNING)
            yield {"event": StreamEventType.STATE.value, "data": {"state": AgentState.PLANNING.value, "step": loop_count}}

            # Call LLM Non-Streaming for Tool Selection or Final Response
            try:
                response = await self.llm.chat_complete(
                    messages=messages,
                    tools=tools_for_role if tools_for_role else None,
                    temperature=0.2,
                )
            except Exception as e:
                logger.error(f"LLM Chat Error in agent loop: {e}")
                err_msg = f"⚠️ **AI Engine Error**: {str(e)}"
                yield {"event": StreamEventType.TOKEN.value, "data": {"delta": err_msg}}
                yield {"event": StreamEventType.ERROR.value, "data": {"error": str(e)}}
                final_answer = err_msg
                break

            choices = response.get("choices", [])
            if not choices:
                break

            msg = choices[0].get("message", {})
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            # A. If Model Wants to Call Tools
            if tool_calls:
                state.transition(AgentState.EXECUTING)
                yield {"event": StreamEventType.STATE.value, "data": {"state": AgentState.EXECUTING.value}}

                # Append assistant message with tool calls to prompt buffer
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })

                for tc in tool_calls:
                    state.increment_tool_call()
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    tool_call_id = tc.get("id", f"call_{state.tool_call_count}")

                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}

                    # Emit Tool Start Event
                    yield {
                        "event": StreamEventType.TOOL_CALL.value,
                        "data": {"tool": tool_name, "arguments": args, "tool_call_id": tool_call_id},
                    }

                    # Execute Tool via Gateway
                    tool = self.registry.get_tool(tool_name)
                    if not tool:
                        res_data = {"error": f"Tool '{tool_name}' not recognized."}
                        status = ToolExecutionStatus.ERROR
                    else:
                        tool_res = await tool.execute(
                            arguments=args,
                            caller_id=user_id,
                            caller_role=user_role,
                            session_id=session_id,
                            confirmation_token=confirmation_token,
                        )
                        status = tool_res.status
                        res_data = tool_res.result or {"error": tool_res.error_message}

                        # Emit Specialized Visual Cards if medicine results
                        if tool_name in ["search_medicines", "suggest_medicines_for_symptoms"] and isinstance(res_data, dict):
                            meds = res_data.get("medicines") or res_data.get("otc_suggestions") or []
                            if meds:
                                yield {"event": StreamEventType.MEDICINE_CARDS.value, "data": {"medicines": meds}}

                        # Emit Confirmation Prompt Event if confirmation required
                        if tool_res.requires_confirmation:
                            yield {
                                "event": StreamEventType.CONFIRMATION_REQUIRED.value,
                                "data": {
                                    "token": tool_res.confirmation_token,
                                    "prompt": tool_res.confirmation_prompt,
                                    "details": res_data,
                                },
                            }

                        # Log Audit Event for Admin Mutations
                        if tool_res.metadata and tool_res.metadata.get("action"):
                            await self.audit.log_action(
                                actor_id=user_id,
                                actor_role=user_role,
                                session_id=session_id,
                                action=tool_res.metadata["action"],
                                resource_type="USER" if "user" in tool_name else "MEDICINE",
                                resource_id=tool_res.metadata.get("resource_id", "unknown"),
                                tool_name=tool_name,
                                status=tool_res.status.value,
                                confirmation_required=tool_res.requires_confirmation,
                                confirmation_received=bool(confirmation_token),
                                metadata=tool_res.metadata,
                            )

                    # Emit Tool Result Event
                    yield {
                        "event": StreamEventType.TOOL_RESULT.value,
                        "data": {"tool": tool_name, "status": status.value, "result": res_data},
                    }

                    # Feed tool result back into context
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(res_data, ensure_ascii=False),
                    })

                # Loop continues back to LLM with tool results in context!
                continue

            # B. If Model Emitted Final Text (No More Tools)
            else:
                state.transition(AgentState.STREAMING)
                yield {"event": StreamEventType.STATE.value, "data": {"state": AgentState.STREAMING.value}}

                # Stream out the content tokens in chunks
                final_answer = content
                chunk_size = 30
                for i in range(0, len(content), chunk_size):
                    chunk = content[i : i + chunk_size]
                    yield {"event": StreamEventType.TOKEN.value, "data": {"delta": chunk}}

                break

        # 5. State: COMPLETE
        state.transition(AgentState.COMPLETE)
        yield {"event": StreamEventType.STATE.value, "data": {"state": AgentState.COMPLETE.value}}
        yield {"event": StreamEventType.DONE.value, "data": {"finish_reason": "stop", "full_content": final_answer}}
