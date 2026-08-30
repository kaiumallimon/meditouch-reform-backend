import json
import time
import inspect
import hashlib
import uuid
from typing import AsyncGenerator, List, Dict, Any, Optional
from app.modules.agent.schemas.chat import AgentState, StreamEventType, SessionType
from app.modules.agent.schemas.tools import ToolExecutionStatus
from app.modules.agent.state import AgentExecutionState
from app.modules.agent.llm.base import LLMProvider
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.security.audit import AgentAuditService
from app.modules.agent.security.policy import CallerContext
from app.modules.agent.assembler import ResponseAssembler
from app.modules.agent.prompts.user_prompt import USER_AGENT_SYSTEM_PROMPT
from app.modules.agent.prompts.admin_prompt import ADMIN_AGENT_SYSTEM_PROMPT
from app.core.logging import logger

MAX_AGENT_STEPS = 8
MAX_TOOL_CALLS = 12
MAX_EXECUTION_TIME_SECONDS = 35.0
MAX_TOOL_RESULT_STRING_LENGTH = 4000
MAX_SAME_TOOL_RETRIES = 2   # max times the same tool+args can be called before being short-circuited


def _args_hash(tool_name: str, args: Dict[str, Any]) -> str:
    """Stable hash of tool_name + normalized arguments for dedup detection."""
    normalized = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(f"{tool_name}:{normalized}".encode()).hexdigest()


class AgentOrchestrator:
    """
    Autonomous ReAct loop planner and executor with centralized ResponseAssembler.

    Core Invariants:
    1. Stable Response ID: Each assistant response turn has a stable `response_id` across all events.
    2. Tool Result ≠ UI Event: Tool results (e.g. search_medicines) remain internal and are buffered
       in ResponseAssembler. Tools do NOT directly emit visual UI cards to the client during execution.
    3. Real-Time Text Streaming: Text tokens stream immediately in real time.
    4. Structured UI On Completion: Visual cards (e.g., medicine_cards) are assembled and emitted
       strictly during response finalization / response_complete.
    5. Deduplication & Loop Protection: Identical (tool, args_hash) calls reuse cached results.
    6. Terminal Clarification: When clarification is needed, the turn terminates immediately
       and buffered UI components are discarded without emission.
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
        task_context_injection: Optional[str] = None,
        task_context: Optional[Dict[str, Any]] = None,
        response_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # 0. Generate or use stable response_id
        active_response_id = response_id or f"resp_{uuid.uuid4().hex[:12]}"
        assembler = ResponseAssembler(response_id=active_response_id)

        state = AgentExecutionState(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            session_type=session_type,
        )

        # Per-run tool result cache: {args_hash → (result_data, status)}
        _tool_result_cache: Dict[str, Any] = {}
        # Per-run same-tool retry counter: {args_hash → call_count}
        _tool_retry_counter: Dict[str, int] = {}

        # 1. State: RECEIVED
        yield {
            "event": StreamEventType.STATE.value,
            "data": {"state": AgentState.RECEIVED.value, "response_id": active_response_id},
        }

        # 2. State: AUTHENTICATING & Context Resolution
        state.transition(AgentState.AUTHENTICATING)
        yield {
            "event": StreamEventType.STATE.value,
            "data": {"state": AgentState.AUTHENTICATING.value, "response_id": active_response_id},
        }

        # Authoritative system prompt and tool schema selection
        is_admin_mode = (session_type == SessionType.ADMIN and user_role in ["ADMIN", "DEVELOPER"])
        system_prompt = ADMIN_AGENT_SYSTEM_PROMPT if is_admin_mode else USER_AGENT_SYSTEM_PROMPT
        tools_for_context = self.registry.get_schemas_for_context(user_role, session_type)

        # 3. Assemble Messages Envelope
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if task_context_injection:
            messages.append({
                "role": "system",
                "content": task_context_injection,
            })

        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        start_time = time.time()
        loop_count = 0
        final_answer = ""
        active_model_tag = getattr(self.llm, "model_tag", "AI Model")

        caller_ctx = CallerContext(
            caller_id=user_id,
            caller_role=user_role,
            session_id=session_id,
            session_type=session_type,
            is_authenticated=(user_id not in ["guest_user", "anonymous", ""]),
        )

        # 4. State: PLANNING & Autonomous ReAct Execution Loop
        while loop_count < MAX_AGENT_STEPS:
            loop_count += 1
            state.increment_step()

            if (time.time() - start_time) > MAX_EXECUTION_TIME_SECONDS:
                logger.warning(f"Agent turn timed out for session {session_id}")
                assembler.clear()
                yield {
                    "event": StreamEventType.ERROR.value,
                    "data": {"error": "Execution time limit exceeded.", "response_id": active_response_id},
                }
                break

            state.transition(AgentState.PLANNING)
            yield {
                "event": StreamEventType.STATE.value,
                "data": {"state": AgentState.PLANNING.value, "step": loop_count, "response_id": active_response_id},
            }

            # Call LLM Non-Streaming for Tool Selection or Final Response
            try:
                response = await self.llm.chat_complete(
                    messages=messages,
                    tools=tools_for_context if tools_for_context else None,
                    temperature=0.2,
                )
            except Exception as e:
                logger.error(f"LLM Chat Error in agent loop: {e}")
                err_msg = f"⚠️ **AI Engine Error**: {str(e)}"
                assembler.clear()
                yield {
                    "event": StreamEventType.TOKEN.value,
                    "data": {"delta": err_msg, "response_id": active_response_id},
                }
                yield {
                    "event": StreamEventType.ERROR.value,
                    "data": {"error": str(e), "response_id": active_response_id},
                }
                final_answer = err_msg
                break

            active_model_tag = response.get("_tag") or getattr(self.llm, "model_tag", "AI Model")
            yield {
                "event": "model_info",
                "data": {
                    "tag": active_model_tag,
                    "provider": response.get("_provider"),
                    "model": response.get("_model"),
                    "response_id": active_response_id,
                },
            }

            choices = response.get("choices", [])
            if not choices:
                break

            msg = choices[0].get("message", {})
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            # A. If Model Wants to Call Tools
            if tool_calls:
                state.transition(AgentState.EXECUTING)
                yield {
                    "event": StreamEventType.STATE.value,
                    "data": {"state": AgentState.EXECUTING.value, "response_id": active_response_id},
                }

                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })

                for tc in tool_calls:
                    if state.tool_call_count >= MAX_TOOL_CALLS:
                        logger.warning(f"Max tool calls ({MAX_TOOL_CALLS}) reached in turn {session_id}")
                        break

                    state.increment_tool_call()
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    tool_call_id = tc.get("id", f"call_{state.tool_call_count}")

                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}

                    # ── Tool Call Deduplication ───────────────────────────────
                    call_hash = _args_hash(tool_name, args)
                    retry_count = _tool_retry_counter.get(call_hash, 0)

                    if call_hash in _tool_result_cache and retry_count >= MAX_SAME_TOOL_RETRIES:
                        logger.warning(
                            f"[Dedup] Tool '{tool_name}' called with identical args {retry_count + 1} times — "
                            f"reusing cached result for session {session_id}"
                        )
                        cached_res_data, cached_status = _tool_result_cache[call_hash]

                        yield {
                            "event": StreamEventType.TOOL_CALL.value,
                            "data": {
                                "tool": tool_name,
                                "arguments": args,
                                "tool_call_id": tool_call_id,
                                "cached": True,
                                "response_id": active_response_id,
                            },
                        }
                        yield {
                            "event": StreamEventType.TOOL_RESULT.value,
                            "data": {
                                "tool": tool_name,
                                "status": cached_status.value,
                                "result": cached_res_data,
                                "cached": True,
                                "response_id": active_response_id,
                            },
                        }

                        # Buffer into ResponseAssembler
                        assembler.record_tool_result(tool_name, args, cached_res_data)

                        sanitized_content = json.dumps(cached_res_data, ensure_ascii=False, default=str)
                        if len(sanitized_content) > MAX_TOOL_RESULT_STRING_LENGTH:
                            sanitized_content = sanitized_content[:MAX_TOOL_RESULT_STRING_LENGTH] + "... [TRUNCATED_OUTPUT]"

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": f"[CACHED RESULT — tool was already called with identical arguments]\n{sanitized_content}",
                        })
                        continue

                    _tool_retry_counter[call_hash] = retry_count + 1

                    # Emit Tool Start Event
                    yield {
                        "event": StreamEventType.TOOL_CALL.value,
                        "data": {
                            "tool": tool_name,
                            "arguments": args,
                            "tool_call_id": tool_call_id,
                            "response_id": active_response_id,
                        },
                    }

                    # Execute Tool via Gateway with Runtime Authorization
                    tool = self.registry.get_tool(tool_name)
                    if not tool:
                        res_data = {"error": f"Tool '{tool_name}' not recognized."}
                        status = ToolExecutionStatus.ERROR
                    else:
                        is_auth, auth_err = self.registry.authorize_execution(tool, caller_ctx)
                        if not is_auth:
                            logger.warning(f"Security Policy Blocked '{tool_name}' for {user_role}:{user_id}: {auth_err}")
                            status = ToolExecutionStatus.PERMISSION_DENIED
                            res_data = {"error": auth_err or "Permission denied."}
                        else:
                            # Build extra kwargs selectively
                            _sig = inspect.signature(tool.execute)
                            _extra_kwargs: Dict[str, Any] = {}
                            _has_var_kw = any(
                                p.kind == inspect.Parameter.VAR_KEYWORD
                                for p in _sig.parameters.values()
                            )
                            _named = set(_sig.parameters)
                            if _has_var_kw or "original_user_message" in _named:
                                _extra_kwargs["original_user_message"] = user_message
                            if _has_var_kw or "task_context" in _named:
                                if task_context:
                                    _extra_kwargs["task_context"] = task_context

                            tool_res = await tool.execute(
                                arguments=args,
                                caller_id=user_id,
                                caller_role=user_role,
                                session_id=session_id,
                                confirmation_token=confirmation_token,
                                **_extra_kwargs,
                            )
                            status = tool_res.status
                            res_data = tool_res.result or {"error": tool_res.error_message}

                            # Cache successful results for dedup
                            if status not in (ToolExecutionStatus.ERROR, ToolExecutionStatus.PERMISSION_DENIED):
                                _tool_result_cache[call_hash] = (res_data, status)

                            # Record in ResponseAssembler (buffered internally, NOT emitted as UI yet)
                            assembler.record_tool_result(tool_name, args, res_data)

                            # ── Clarification Required — TERMINAL STATE ───────────
                            if tool_res.requires_clarification or status == ToolExecutionStatus.CLARIFICATION_REQUIRED:
                                assembler.clear()  # Discard any buffered UI cards
                                clarif_data = tool_res.clarification_payload or (res_data if isinstance(res_data, dict) else {})
                                yield {
                                    "event": StreamEventType.CLARIFICATION_REQUIRED.value,
                                    "data": {**clarif_data, "response_id": active_response_id},
                                }
                                state.transition(AgentState.COMPLETE)
                                yield {
                                    "event": StreamEventType.STATE.value,
                                    "data": {"state": AgentState.COMPLETE.value, "response_id": active_response_id},
                                }
                                yield {
                                    "event": StreamEventType.DONE.value,
                                    "data": {
                                        "finish_reason": "clarification_required",
                                        "full_content": "",
                                        "model_name": active_model_tag,
                                        "clarification": clarif_data,
                                        "response_id": active_response_id,
                                    },
                                }
                                return

                            # Emit Confirmation Prompt Event if confirmation required
                            if tool_res.requires_confirmation:
                                yield {
                                    "event": StreamEventType.CONFIRMATION_REQUIRED.value,
                                    "data": {
                                        "token": tool_res.confirmation_token,
                                        "prompt": tool_res.confirmation_prompt,
                                        "details": res_data,
                                        "response_id": active_response_id,
                                    },
                                }

                            # Log Audit Event for Admin Mutations
                            if tool_res.metadata and tool_res.metadata.get("action"):
                                await self.audit.log_action(
                                    actor_id=user_id,
                                    actor_role=user_role,
                                    session_id=session_id,
                                    action=tool_res.metadata["action"],
                                    resource_type="USER" if "user" in tool_name else ("DOCTOR" if "doctor" in tool_name else "MEDICINE"),
                                    resource_id=tool_res.metadata.get("resource_id", "unknown"),
                                    tool_name=tool_name,
                                    status=tool_res.status.value,
                                    confirmation_required=tool_res.requires_confirmation,
                                    confirmation_received=bool(confirmation_token),
                                    metadata=tool_res.metadata,
                                )

                    # Emit Tool Result Event (data notification only — does not render visual UI)
                    yield {
                        "event": StreamEventType.TOOL_RESULT.value,
                        "data": {
                            "tool": tool_name,
                            "status": status.value,
                            "result": res_data,
                            "response_id": active_response_id,
                        },
                    }

                    # Sanitize and truncate tool result string
                    sanitized_content = json.dumps(res_data, ensure_ascii=False, default=str)
                    if len(sanitized_content) > MAX_TOOL_RESULT_STRING_LENGTH:
                        sanitized_content = sanitized_content[:MAX_TOOL_RESULT_STRING_LENGTH] + "... [TRUNCATED_OUTPUT]"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": sanitized_content,
                    })

                continue

            # B. If Model Emitted Final Text (No More Tools)
            else:
                state.transition(AgentState.STREAMING)
                yield {
                    "event": StreamEventType.STATE.value,
                    "data": {"state": AgentState.STREAMING.value, "response_id": active_response_id},
                }

                # Stream out content tokens in real time
                final_answer = content
                chunk_size = 30
                for i in range(0, len(content), chunk_size):
                    chunk = content[i : i + chunk_size]
                    yield {
                        "event": StreamEventType.TOKEN.value,
                        "data": {"delta": chunk, "response_id": active_response_id},
                    }

                break

        # 5. State: FINALIZING & Structured UI Assembly
        # Assembled structured UI components (e.g. medicine cards) are emitted strictly upon finalization
        state.transition(AgentState.FINALIZING)
        medicine_cards = assembler.get_medicine_cards(limit=5)
        structured_components = assembler.assemble_final_components()

        if medicine_cards:
            # Emit finalized medicine cards event right after text streaming finishes
            yield {
                "event": StreamEventType.MEDICINE_CARDS.value,
                "data": {
                    "medicines": medicine_cards,
                    "response_id": active_response_id,
                },
            }

        # 6. State: COMPLETE
        state.transition(AgentState.COMPLETE)
        yield {
            "event": StreamEventType.STATE.value,
            "data": {"state": AgentState.COMPLETE.value, "response_id": active_response_id},
        }
        yield {
            "event": StreamEventType.DONE.value,
            "data": {
                "finish_reason": "stop",
                "full_content": final_answer,
                "model_name": active_model_tag,
                "response_id": active_response_id,
                "medicine_cards": medicine_cards,
                "components": structured_components,
            },
        }
