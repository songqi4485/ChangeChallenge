from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import asyncio
import asyncio.proactor_events
import asyncio.selector_events
import locale
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit


WORKTREE = Path(__file__).resolve().parents[2]
INTERPRETER = Path(r"D:\APP\Python 3.13\挑战杯\.venv\Scripts\python.exe")
BASELINE_HEAD = "e032f953f5bbfb58f81f79f66ac0495cf0fd51b8"
CONFIG_FILES = (
    "app.yaml",
    "evals.yaml",
    "providers.yaml",
    "prompts.yaml",
    "voice.yaml",
    "rag.yaml",
    "structured_slices.yaml",
    "memory.yaml",
    "voice_terminology.yaml",
    "voice_pronunciation.yaml",
)


def _prepare_providers_text(text: str) -> str:
    defaults = list(
        re.finditer(
            r"(?m)^    default:[ \t]*(?:deepseek|qwen|mock)[ \t]*$", text
        )
    )
    if len(defaults) != 1:
        raise RuntimeError(
            "unexpected AC02 config shape in providers.yaml: llm.default"
        )
    match = defaults[0]
    text = text[: match.start()] + "    default: mock" + text[match.end() :]
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped.startswith("api_key:"):
            indent = line[: len(line) - len(stripped)]
            lines.append(f'{indent}api_key: ""')
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


BASELINE_TESTS = (
    "tests/integration/app_loop/test_answer_contract_compatibility.py",
    "tests/unit/core/test_answer_contracts.py",
    "tests/integration/app_loop/test_langgraph_recovery.py",
    "tests/unit/feedback/test_checkpoint_persistence.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
    "tests/contracts/test_voice_ws_v1_contract.py",
    "tests/integration/voice_loop/test_voice_trace_privacy.py",
    "tests/integration/voice_loop/test_answer_streaming_ws.py",
)
GUARD_TESTS = ("tests/unit/core/test_ac02_isolation.py",)
R05_TESTS = (
    "tests/unit/core/test_ac02_isolation.py",
    "tests/unit/core/test_runtime_settings.py",
    "tests/unit/core/test_r05_budget.py",
    "tests/unit/generation/test_r05_call_options.py",
    "tests/integration/app_loop/test_r05_request_budget_wiring.py",
    "tests/unit/services/test_r05_model_transport.py",
    "tests/unit/services/test_r05_cost.py",
    "tests/integration/app_loop/test_r05_runtime_cost_wiring.py",
    "tests/unit/services/test_r05_recovery_generation.py",
    "tests/unit/evaluation/test_r05_topic_summaries.py",
    "tests/integration/app_loop/test_r05_recovery_terminal.py",
    "tests/integration/app_loop/test_r05_recovery_history.py",
    "tests/integration/app_loop/test_r05_recovery_events.py",
    "tests/integration/app_loop/test_answer_event_stream.py",
    "tests/unit/services/test_answer_events.py",
    "tests/unit/self_check/test_r05_scene_entity.py",
    "tests/integration/voice_loop/test_r05_recovery_voice.py",
    "tests/unit/evaluation/test_agent_benchmark.py",
    "tests/integration/app_loop/test_r05_demo_acceptance.py",
    "tests/e2e/scenarios/test_eval_and_deployment_scripts.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
    "tests/unit/generation/test_drafting_coordinator.py",
    "tests/integration/app_loop/test_agent_decision_execution.py",
    "tests/e2e/scenarios/test_self_check_failover.py",
    "tests/integration/app_loop/test_four_stage_runtime.py",
)
AC04_TESTS = (
    "tests/unit/core/test_request_budget.py",
    "tests/unit/core/test_runtime_settings.py",
    "tests/unit/services/test_cancellable_io.py",
    "tests/unit/services/test_model_client.py",
    "tests/unit/services/test_model_runtime.py",
    "tests/unit/services/test_deepseek_client.py",
    "tests/unit/services/test_qwen_client.py",
    "tests/unit/services/test_embedding_provider.py",
    "tests/unit/evaluation/test_embedding_validation.py",
    "tests/unit/knowledge/test_retrieval_prefetch.py",
    "tests/unit/agent/test_langgraph_checkpointer.py",
    "tests/unit/agent/test_graph_contracts.py",
    "tests/integration/app_loop/test_langgraph_recovery.py",
    "tests/integration/app_loop/test_langgraph_runtime.py",
)
AC05_TESTS = (
    "tests/e2e/scenarios/test_eval_and_deployment_scripts.py",
    "tests/e2e/scenarios/test_text_qa_flow.py",
)
AC06_TESTS = (
    "tests/unit/input",
    "tests/unit/agent/test_context_resolution.py",
    "tests/e2e/scenarios/test_context_resolution_20_turns.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
)
AC07_TESTS = (
    "tests/unit/knowledge/test_rag_config.py",
    "tests/unit/knowledge/test_retrieval_parallel.py",
    "tests/unit/knowledge/test_structured_slices.py",
    "tests/unit/knowledge/test_structured_slice_cli.py",
    "tests/unit/knowledge/test_structured_slice_transactions.py",
    "tests/unit/knowledge/test_repository.py",
    "tests/unit/knowledge/test_bm25_index.py",
    "tests/unit/knowledge/test_sqlite_vector_store.py",
    "tests/unit/knowledge/test_parent_channel_filter_sync.py",
    "tests/unit/knowledge/test_parent_snapshot_performance.py",
    "tests/unit/knowledge/test_retrieval_planner.py",
    "tests/unit/knowledge/test_filter_rules_consistency.py",
    "tests/unit/knowledge/test_evidence_gate_states.py",
    "tests/unit/knowledge/test_requirement_preserving_selection.py",
    "tests/unit/knowledge/test_keyword_index_snapshot.py",
    "tests/integration/rag_pipeline/test_adaptive_hybrid_retrieval.py",
    "tests/integration/rag_pipeline/test_parameter_table_retrieval.py",
    "tests/integration/rag_pipeline/test_structured_slice_retrieval.py",
    "tests/integration/rag_pipeline/test_evidence_relevance_gate.py",
    "tests/integration/rag_pipeline/test_scene_binding_retrieval.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
)
AC08_TESTS = (
    "tests/unit/knowledge/test_retrieval_prefetch.py",
    "tests/integration/rag_pipeline/test_retrieval_refinement.py",
    "tests/integration/rag_pipeline/test_targeted_retrieve_more.py",
    "tests/integration/app_loop/test_langgraph_runtime.py",
)
AC09_TESTS = (
    "tests/unit/prompts",
    "tests/unit/generation/test_evidence_sketch.py",
    "tests/integration/answer_pipeline/test_generation_preparation.py",
    "tests/integration/app_loop/test_app_pipeline_model_generation.py",
)
AC10_TESTS = (
    "tests/unit/generation",
    "tests/integration/answer_pipeline/test_generation_pipeline.py",
    "tests/integration/answer_pipeline/test_memory_cannot_be_fact_source.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
    "tests/integration/answer_pipeline/test_unified_science_answer_policy.py",
    "tests/integration/app_loop/test_app_pipeline_model_generation.py",
)
AC11_TESTS = (
    "tests/unit/self_check",
    "tests/integration/answer_pipeline/test_canonical_self_check.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
    "tests/integration/app_loop/test_langgraph_runtime.py",
    "tests/integration/app_loop/test_langgraph_recovery.py",
)
AC12_TESTS = (
    "tests/integration/app_loop/test_agent_decision_execution.py",
    "tests/integration/app_loop/test_langgraph_runtime.py",
    "tests/e2e/scenarios/test_self_check_failover.py",
    "tests/integration/answer_pipeline/test_canonical_self_check.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
    "tests/unit/agent/test_terminal_clarification.py",
)
AC13_TESTS = (
    "tests/integration/app_loop/test_four_stage_runtime.py",
    "tests/integration/app_loop/test_langgraph_runtime.py",
    "tests/integration/app_loop/test_langgraph_recovery.py",
    "tests/integration/app_loop/test_agent_decision_execution.py",
    "tests/integration/app_loop/test_answer_contract_compatibility.py",
)
AC14_TESTS = (
    "tests/integration/app_loop/test_langgraph_recovery.py",
    "tests/unit/agent/test_langgraph_checkpointer.py",
    "tests/unit/agent/test_graph_contracts.py",
    "tests/integration/app_loop/test_langgraph_runtime.py",
)
AC15_TESTS = (
    "tests/integration/feedback_loop",
    "tests/unit/feedback",
    "tests/e2e/scenarios/test_feedback_flow.py",
)
AC16_TESTS = (
    "tests/integration/voice_loop/test_turn_task_cancellation.py",
    "tests/integration/voice_loop/test_orchestrated_voice_pipeline.py",
    "tests/integration/voice_loop/test_streaming_voice_loop.py",
    "tests/integration/voice_loop/test_barge_in_feedback.py",
    "tests/integration/memory_service/test_parallel_memory_rag.py",
    "tests/integration/memory_async/test_answer_survives_async_failures.py",
    "tests/unit/memory/test_grpc_memory_port.py",
    "tests/unit/memory/test_memory_retrieval.py",
    "tests/unit/memory/test_memory_controller_config.py",
    "tests/unit/voice/test_voice_websocket_server.py",
    "tests/contracts/test_voice_ws_v1_contract.py",
)
AC17_TESTS = (
    "tests/integration/app_loop/test_four_stage_runtime.py",
    "tests/integration/app_loop/test_langgraph_recovery.py",
    "tests/integration/answer_pipeline/test_answer_generation_regressions.py",
    "tests/integration/feedback_loop/test_text_chain_feedback_entry.py",
    "tests/integration/voice_loop/test_turn_task_cancellation.py",
    "tests/unit/input/test_entity_topic_separation.py",
    "tests/unit/self_check/test_question_completion_state.py",
    "tests/unit/services/test_compute_worker.py",
    "tests/unit/services/test_answer_events.py",
    "tests/unit/services/test_sse_stream.py",
    "tests/integration/app_loop/test_answer_event_stream.py",
)
BENCHMARK_TESTS = (
    "tests/unit/evaluation/test_agent_benchmark.py",
    "tests/unit/evaluation/test_candidate_suite.py",
    "tests/unit/evaluation/test_direct_answer_convergence.py",
    "tests/unit/evaluation/test_memory_cleanup_tool.py",
    "tests/unit/test_cost_ledger.py",
)
VOICE_ANSWER_STREAM_TESTS = (
    "tests/unit/voice/test_voice_hotwords.py",
    "tests/unit/voice/test_qwen_asr.py",
    "tests/unit/voice/test_cosyvoice_tts.py",
    "tests/unit/voice/test_cosyvoice_server.py",
    "tests/unit/core/test_ac02_isolation.py",
    "tests/unit/core/test_runtime_settings.py",
    "tests/contracts/test_voice_ws_v1_contract.py",
    "tests/contracts/test_voice_vr_governance.py",
    "tests/unit/services/test_answer_events.py",
    "tests/unit/services/test_sse_stream.py",
    "tests/unit/services/test_model_client.py",
    "tests/unit/services/test_model_runtime.py",
    "tests/unit/services/test_qwen_client.py",
    "tests/unit/services/test_deepseek_client.py",
    "tests/unit/services/test_r05_model_transport.py",
    "tests/unit/services/test_r05_recovery_generation.py",
    "tests/unit/voice/test_voice_orchestrator.py",
    "tests/unit/voice/test_voice_websocket_server.py",
    "tests/unit/voice/test_voice_transport.py",
    "tests/unit/voice/test_answer_stream_projection.py",
    "tests/integration/app_loop/test_answer_event_stream.py",
    "tests/integration/app_loop/test_r05_recovery_events.py",
    "tests/integration/app_loop/test_r05_recovery_terminal.py",
    "tests/integration/voice_loop/test_turn_task_cancellation.py",
    "tests/integration/voice_loop/test_processing_heartbeat.py",
    "tests/integration/voice_loop/test_disconnect_reconnect.py",
    "tests/integration/voice_loop/test_r05_recovery_voice.py",
    "tests/integration/voice_loop/test_voice_trace_privacy.py",
    "tests/integration/voice_loop/test_tts_failure_degradation.py",
)
ALL_TESTS = tuple(
    dict.fromkeys(
        (
            *BENCHMARK_TESTS,
            *AC04_TESTS,
            *AC05_TESTS,
            *AC06_TESTS,
            *AC07_TESTS,
            *AC08_TESTS,
            *AC09_TESTS,
            *AC10_TESTS,
            *AC11_TESTS,
            *AC12_TESTS,
            *AC13_TESTS,
            *AC14_TESTS,
            *AC15_TESTS,
            *AC16_TESTS,
            *AC17_TESTS,
            *VOICE_ANSWER_STREAM_TESTS,
            # CP-finalfix/CP02 专项重放文件：不属于任何历史 AC 套件，
            # 仅追加进全量集合，不改动任何已冻结的分套件选择集。
            "tests/integration/app_loop/test_r05_systematic_recovery.py",
            # R01 F02：比较维度与可靠证据反证的已登记 RED。
            "tests/integration/app_loop/test_r01_f02_staged.py",
            # R01 F04：恢复引用归属的已登记 RED。
            "tests/integration/app_loop/test_r01_f04_staged.py",
        )
    )
)
_CHILD_ENTRYPOINTS = {
    "--child-probe",
    "--pytest-probe",
    "--compute-worker",
    "--app-cli",
    "--pytest-runner",
    "--feedback-query",
    "--feedback-rewrite",
    "--eval-script",
    "--no-voice-eval",
}
_ACTIVE: "OfflineEnvironment | None" = None
_SESSION_VIOLATIONS: list[dict[str, str]] = []
_PYTEST_HOOK_ACTIVE = False
_ORIGINAL_POPEN = subprocess.Popen
_ORIGINAL_SENDMSG: Any = None
_ORIGINAL_PLATFORM_SYSTEM = platform.system
_ORIGINAL_OS_SYSTEM = os.system
_ORIGINAL_OS_POPEN = os.popen


class Ac02GuardError(RuntimeError):
    def __init__(self, category: str, target: str) -> None:
        self.category = category
        self.target = target
        super().__init__(f"AC02 {category} guard rejected {target}")


def guard_errors_only(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        return bool(error.exceptions) and all(
            guard_errors_only(child) for child in error.exceptions
        )
    return isinstance(error, Ac02GuardError)


class _ExpectedBlock:
    def __init__(self, category: str) -> None:
        self.category = category
        self.used = False


class OfflineGuard:
    def __init__(self, environment: "OfflineEnvironment") -> None:
        self.environment = environment
        self.installed = False
        self.expected: list[_ExpectedBlock] = []
        self.unexpected: list[dict[str, str]] = []
        self.registered_loopback_endpoints: set[tuple[str, int, int, int, int]] = set()
        self.socket_endpoints: dict[int, list[tuple[str, int, int, int, int]]] = {}
        self.allow_loopback_rebind = False

    def install(self) -> None:
        if self.installed:
            return
        socket_module = socket

        def guarded_connect(sock, address):
            return self._connect(sock, address)

        def guarded_connect_ex(sock, address):
            return self._connect_ex(sock, address)

        def guarded_bind(sock, address):
            return self._bind(sock, address)

        def guarded_sendto(sock, data, *args, **kwargs):
            return self._sendto(sock, data, *args, **kwargs)

        def guarded_sendmsg(sock, buffers, *args, **kwargs):
            return self._sendmsg(sock, buffers, *args, **kwargs)

        def guarded_ssl_connect(sock, address):
            return self._ssl_connect(sock, address)

        def guarded_close(sock):
            result = _ORIGINAL_SOCKET_CLOSE(sock)
            for endpoint in self.socket_endpoints.pop(id(sock), ()):
                self.registered_loopback_endpoints.discard(endpoint)
            return result

        async def guarded_selector_connect(loop, sock, address):
            host, port = self._host_port(address)
            self._validate_target(
                "network",
                host,
                port,
                family=sock.family,
                sock_type=self._socket_type(sock),
                proto=sock.proto,
            )
            return await _ORIGINAL_SELECTOR_CONNECT(loop, sock, address)

        async def guarded_proactor_connect(loop, sock, address):
            host, port = self._host_port(address)
            self._validate_target(
                "network",
                host,
                port,
                family=sock.family,
                sock_type=self._socket_type(sock),
                proto=sock.proto,
            )
            return await _ORIGINAL_PROACTOR_CONNECT(loop, sock, address)

        async def guarded_selector_sendto(loop, sock, data, address):
            host, port = self._host_port(address)
            self._validate_target(
                "network",
                host,
                port,
                family=sock.family,
                sock_type=self._socket_type(sock),
                proto=sock.proto,
            )
            return await _ORIGINAL_SELECTOR_SENDTO(loop, sock, data, address)

        async def guarded_proactor_sendto(loop, sock, data, address):
            host, port = self._host_port(address)
            self._validate_target(
                "network",
                host,
                port,
                family=sock.family,
                sock_type=self._socket_type(sock),
                proto=sock.proto,
            )
            return await _ORIGINAL_PROACTOR_SENDTO(loop, sock, data, address)

        socket_module.getaddrinfo = self._getaddrinfo
        socket_module.create_connection = self._create_connection
        socket_module.socket.connect = guarded_connect
        socket_module.socket.connect_ex = guarded_connect_ex
        socket_module.socket.bind = guarded_bind
        socket_module.socket.sendto = guarded_sendto
        socket_module.socket.close = guarded_close
        if hasattr(socket_module.socket, "sendmsg"):
            global _ORIGINAL_SENDMSG
            _ORIGINAL_SENDMSG = socket_module.socket.sendmsg
            socket_module.socket.sendmsg = guarded_sendmsg
        asyncio.selector_events.BaseSelectorEventLoop.sock_connect = guarded_selector_connect
        asyncio.selector_events.BaseSelectorEventLoop.sock_sendto = guarded_selector_sendto
        asyncio.proactor_events.BaseProactorEventLoop.sock_connect = guarded_proactor_connect
        asyncio.proactor_events.BaseProactorEventLoop.sock_sendto = guarded_proactor_sendto
        ssl.SSLSocket.connect = guarded_ssl_connect
        sqlite3.connect = self._sqlite_connect
        sqlite3.dbapi2.connect = self._sqlite_connect
        platform.system = lambda: "Windows"

        guard = self

        class GuardedPopen(_ORIGINAL_POPEN):
            def __init__(popen_self, *popen_args, **kwargs):
                guard._prepare_popen(popen_args, kwargs)
                super().__init__(*popen_args, **kwargs)

        subprocess.Popen = GuardedPopen
        os.system = self._system
        os.popen = self._popen_text
        self.installed = True

    def restore(self) -> None:
        if not self.installed:
            return
        socket.getaddrinfo = _ORIGINAL_GETADDRINFO
        socket.create_connection = _ORIGINAL_CREATE_CONNECTION
        socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
        socket.socket.connect_ex = _ORIGINAL_SOCKET_CONNECT_EX
        socket.socket.bind = _ORIGINAL_SOCKET_BIND
        socket.socket.sendto = _ORIGINAL_SENDTO
        socket.socket.close = _ORIGINAL_SOCKET_CLOSE
        if _ORIGINAL_SENDMSG is not None:
            socket.socket.sendmsg = _ORIGINAL_SENDMSG
        ssl.SSLSocket.connect = _ORIGINAL_SSL_CONNECT
        asyncio.selector_events.BaseSelectorEventLoop.sock_connect = _ORIGINAL_SELECTOR_CONNECT
        asyncio.selector_events.BaseSelectorEventLoop.sock_sendto = _ORIGINAL_SELECTOR_SENDTO
        asyncio.proactor_events.BaseProactorEventLoop.sock_connect = _ORIGINAL_PROACTOR_CONNECT
        asyncio.proactor_events.BaseProactorEventLoop.sock_sendto = _ORIGINAL_PROACTOR_SENDTO
        sqlite3.connect = _ORIGINAL_SQLITE_CONNECT
        sqlite3.dbapi2.connect = _ORIGINAL_SQLITE_DBAPI_CONNECT
        subprocess.Popen = _ORIGINAL_POPEN
        platform.system = _ORIGINAL_PLATFORM_SYSTEM
        os.system = _ORIGINAL_OS_SYSTEM
        os.popen = _ORIGINAL_OS_POPEN
        self.installed = False

    @contextmanager
    def expect_block(self, category: str) -> Iterator[None]:
        expected = _ExpectedBlock(category)
        self.expected.append(expected)
        try:
            yield
        finally:
            if expected in self.expected:
                self.expected.remove(expected)
            if not expected.used:
                self._record_unexpected(
                    {"category": category, "event": "expected_block_not_triggered"}
                )

    def _record_unexpected(self, event: dict[str, str]) -> None:
        self.unexpected.append(event)
        if event not in _SESSION_VIOLATIONS:
            _SESSION_VIOLATIONS.append(event)

    def block(self, category: str, target: str) -> None:
        safe_target = target.replace(str(self.environment.root), "<temp-root>")
        for expected in reversed(self.expected):
            if expected.category == category and not expected.used:
                expected.used = True
                break
        else:
            self._record_unexpected({"category": category, "target": safe_target})
        raise Ac02GuardError(category, safe_target)

    def is_loopback_port_registered(self, port: int) -> bool:
        return any(endpoint[1] == port for endpoint in self.registered_loopback_endpoints)

    @staticmethod
    def _canonical_loopback(host: object) -> str | None:
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if host == "localhost":
            return "127.0.0.1"
        if host == "::ffff:127.0.0.1":
            return "127.0.0.1"
        return str(host) if host in {"127.0.0.1", "::1"} else None

    def _validate_target(
        self,
        category: str,
        host: object,
        port: int | None,
        *,
        family: int | None = None,
        sock_type: int | None = None,
        proto: int | None = None,
    ) -> None:
        canonical = self._canonical_loopback(host)
        if canonical is not None and isinstance(port, int):
            for endpoint in self.registered_loopback_endpoints:
                ep_host, ep_port, ep_family, ep_type, ep_proto = endpoint
                if canonical != ep_host or port != ep_port:
                    continue
                if family not in (None, 0, ep_family):
                    continue
                if sock_type not in (None, 0, ep_type):
                    continue
                if proto not in (None, 0, ep_proto):
                    continue
                return
        self.block(category, f"{host!r}:{port}")

    @staticmethod
    def _socket_type(sock) -> int:
        mask = getattr(socket, "SOCK_TYPE_MASK", 0)
        return sock.type & mask if mask else sock.type

    @staticmethod
    def _host_port(address: object) -> tuple[object, int | None]:
        if isinstance(address, tuple) and len(address) >= 2:
            port = address[1]
            return address[0], port if isinstance(port, int) else None
        return address, None

    def _getaddrinfo(self, host, port, *args, **kwargs):
        if host is None:
            return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)
        self._validate_target("network", host, port if isinstance(port, int) else None)
        return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)

    def _create_connection(self, address, *args, **kwargs):
        host, port = self._host_port(address)
        self._validate_target("network", host, port)
        return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)

    def _connect(self, sock, address):
        if sock.family == getattr(socket, "AF_UNIX", object()):
            self.block("network", "unix-socket")
        host, port = self._host_port(address)
        self._validate_target(
            "network",
            host,
            port,
            family=sock.family,
            sock_type=self._socket_type(sock),
            proto=sock.proto,
        )
        return _ORIGINAL_SOCKET_CONNECT(sock, address)

    def _connect_ex(self, sock, address):
        host, port = self._host_port(address)
        self._validate_target(
            "network",
            host,
            port,
            family=sock.family,
            sock_type=self._socket_type(sock),
            proto=sock.proto,
        )
        return _ORIGINAL_SOCKET_CONNECT_EX(sock, address)

    def _bind(self, sock, address):
        if sock.family == getattr(socket, "AF_UNIX", object()):
            self.block("network", "unix-socket")
        host, port = self._host_port(address)
        if self._canonical_loopback(host) is None or (
            port != 0 and not self.allow_loopback_rebind
        ):
            self.block("network", f"bind {host!r}:{port}")
        result = _ORIGINAL_SOCKET_BIND(sock, address)
        bound = sock.getsockname()
        endpoint = (
            self._canonical_loopback(bound[0]) or str(bound[0]),
            int(bound[1]),
            sock.family,
            self._socket_type(sock),
            sock.proto,
        )
        self.registered_loopback_endpoints.add(endpoint)
        self.socket_endpoints.setdefault(id(sock), []).append(endpoint)
        return result

    def _sendto(self, sock, data, *args, **kwargs):
        if not args:
            self.block("network", "sendto-without-address")
        host, port = self._host_port(args[-1])
        self._validate_target(
            "network",
            host,
            port,
            family=sock.family,
            sock_type=self._socket_type(sock),
            proto=sock.proto,
        )
        return _ORIGINAL_SENDTO(sock, data, *args, **kwargs)

    def _sendmsg(self, sock, buffers, *args, **kwargs):
        address = kwargs.get("address")
        if address is None and len(args) >= 3:
            address = args[2]
        host, port = self._host_port(address)
        self._validate_target(
            "network",
            host,
            port,
            family=sock.family,
            sock_type=self._socket_type(sock),
            proto=sock.proto,
        )
        # Windows/Python builds without sendmsg never install this wrapper.
        return _ORIGINAL_SENDMSG(sock, buffers, *args, **kwargs)

    def _ssl_connect(self, sock, address):
        host, port = self._host_port(address)
        self._validate_target(
            "network",
            host,
            port,
            family=sock.family,
            sock_type=self._socket_type(sock),
            proto=sock.proto,
        )
        return _ORIGINAL_SSL_CONNECT(sock, address)

    def _sqlite_connect(self, database, *args, **kwargs):
        resolved = self.environment.resolve_sqlite_target(database)
        if resolved is None:
            self.block("sqlite", str(database))
        if str(resolved).startswith("file:"):
            kwargs["uri"] = True
        connection = _ORIGINAL_SQLITE_CONNECT(resolved, *args, **kwargs)
        connection.set_authorizer(self._sqlite_authorizer)
        return connection

    def _sqlite_authorizer(self, action, arg1, arg2, database, trigger):
        del arg2, database, trigger
        if action == sqlite3.SQLITE_ATTACH:
            raw = str(arg1)
            if not Path(raw).is_absolute() or self.environment.resolve_sqlite_target(raw) is None:
                self.block("sqlite", f"ATTACH {raw}")
        return sqlite3.SQLITE_OK

    def _prepare_popen(self, popen_args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        if "shell" in kwargs and kwargs["shell"]:
            self.block("subprocess", "shell=True")
        if "executable" in kwargs:
            self.block("subprocess", "executable-override")
        requested_cwd = kwargs.get("cwd")
        if requested_cwd is not None:
            try:
                if Path(requested_cwd).resolve() != self.environment.root:
                    self.block("subprocess", "cwd-outside-ac02-root")
            except OSError:
                self.block("subprocess", "cwd-unresolvable")
        if not popen_args:
            self.block("subprocess", "missing-command")
        command = popen_args[0]
        if isinstance(command, (list, tuple)):
            arguments = [str(item) for item in command]
        elif isinstance(command, (str, bytes, os.PathLike)):
            arguments = [str(os.fsdecode(command))]
        else:
            self.block("subprocess", type(command).__name__)
        if not self.environment.is_approved_helper_command(arguments):
            self.block("subprocess", " ".join(arguments[:4]))
        kwargs["cwd"] = self.environment.root
        kwargs["env"] = self.environment.child_env

    def _system(self, command):
        self.block("subprocess", str(command)[:120])

    def _popen_text(self, command, *args, **kwargs):
        self.block("subprocess", str(command)[:120])


class OfflineEnvironment:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.configs = self.root / "configs"
        self.guard: OfflineGuard | None = None
        self.child_env = self._build_child_env()
        self.pytest_results: list[dict[str, Any]] = []
        self.pytest_kind = ""

    @classmethod
    def create(cls) -> "OfflineEnvironment":
        root = Path(tempfile.mkdtemp(prefix="ac02-offline-"))
        environment = cls(root)
        environment._prepare()
        os.chdir(environment.root)
        global _ACTIVE
        _ACTIVE = environment
        return environment

    @classmethod
    def load(cls, root: str | Path) -> "OfflineEnvironment":
        environment = cls(Path(root))
        if not (environment.root / ".ac02-offline-root").is_file():
            raise RuntimeError("AC02 root marker is missing")
        os.chdir(environment.root)
        global _ACTIVE
        _ACTIVE = environment
        return environment

    def _prepare(self) -> None:
        (self.root / ".ac02-offline-root").write_text("AC02", encoding="utf-8")
        self.configs.mkdir()
        for name in CONFIG_FILES:
            source = WORKTREE / "configs" / name
            if not source.is_file():
                raise FileNotFoundError(source)
            if name == "providers.yaml":
                (self.configs / name).write_text(
                    _prepare_providers_text(
                        source.read_text(encoding="utf-8")
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
            else:
                shutil.copy2(source, self.configs / name)
        shutil.copytree(WORKTREE / "assets" / "prompts", self.root / "assets" / "prompts")
        for directory in (
            self.root / "data" / "processed",
            self.root / "tmp",
            self.root / "home",
            self.root / "appdata",
            self.root / "localappdata",
            self.root / "reports",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._rewrite_copy(
            self.configs / "providers.yaml",
            (
                ("    default: bge_m3\n", "    default: mock\n"),
            ),
        )
        self._rewrite_copy(
            self.configs / "rag.yaml",
            (
                ("    provider: bge_m3\n", "    provider: mock\n"),
            ),
        )
        self._rewrite_copy(
            self.configs / "voice.yaml",
            (
                ("  asr_provider: qwen3_asr\n" if "  asr_provider: qwen3_asr" in (self.configs / "voice.yaml").read_text(encoding="utf-8") else "  asr_provider: whisper\n", "  asr_provider: mock\n"),
                ("  tts_provider: cosyvoice\n", "  tts_provider: mock\n"),
            ),
        )
        if not INTERPRETER.is_file():
            raise FileNotFoundError(INTERPRETER)

    @staticmethod
    def _rewrite_copy(path: Path, replacements: tuple[tuple[str, str], ...]) -> None:
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            if text.count(old) != 1:
                raise RuntimeError(f"unexpected AC02 config shape in {path.name}: {old!r}")
            text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8", newline="\n")

    def _build_child_env(self) -> dict[str, str]:
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        temp_dir = self.root / "tmp"
        environment = {
            "SYSTEMROOT": system_root,
            "PROCESSOR_ARCHITECTURE": os.environ.get("PROCESSOR_ARCHITECTURE", ""),
            "SYSTEMDRIVE": str(Path(system_root).anchor),
            "WINDIR": system_root,
            "COMSPEC": str(Path(system_root) / "System32" / "cmd.exe"),
            "PATH": f"{Path(system_root) / 'System32'};{system_root}",
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "TMPDIR": str(temp_dir),
            "USERPROFILE": str(self.root / "home"),
            "HOME": str(self.root / "home"),
            "APPDATA": str(self.root / "appdata"),
            "LOCALAPPDATA": str(self.root / "localappdata"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "NO_PROXY": "127.0.0.1,::1,localhost",
            "no_proxy": "127.0.0.1,::1,localhost",
        }
        return environment

    def install_guard(self) -> OfflineGuard:
        guard = OfflineGuard(self)
        guard.install()
        self.guard = guard
        return guard

    def expect_block(self, category: str):
        if self.guard is None:
            raise RuntimeError("AC02 guard is not installed")
        return self.guard.expect_block(category)

    def is_loopback_port_registered(self, port: int) -> bool:
        return self.guard is not None and self.guard.is_loopback_port_registered(port)

    def resolve_sqlite_target(self, database: object) -> str | None:
        if isinstance(database, bytes):
            database = os.fsdecode(database)
        if not isinstance(database, (str, os.PathLike)):
            return None
        raw = os.fspath(database)
        if raw in {":memory:", "file::memory:", "file::memory:?cache=shared"}:
            return raw
        is_uri = raw.startswith("file:")
        suffix = ""
        if raw.startswith("file:"):
            parsed = urlsplit(raw)
            raw = unquote(parsed.path)
            if parsed.netloc:
                raw = f"//{parsed.netloc}{raw}"
            if os.name == "nt" and raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
                raw = raw[1:]
            suffix = f"?{parsed.query}" if parsed.query else ""
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(self.root)
        except ValueError:
            return None
        if is_uri:
            return f"file:{resolved.as_posix()}{suffix}"
        return str(resolved)

    def make_external_sentinel(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="ac02-sentinel-", dir=self.root.parent))

    def make_test_path(self) -> Path:
        parent = self.root / "pytest-test-paths"
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="case-", dir=parent))

    def is_approved_helper_command(self, arguments: list[str]) -> bool:
        if len(arguments) < 7:
            return False
        try:
            if Path(arguments[0]).resolve() != INTERPRETER.resolve():
                return False
        except OSError:
            return False
        prefix = [
            str(INTERPRETER),
            "-I",
            "-B",
            str(Path(__file__).resolve()),
        ]
        if arguments[:4] != prefix or arguments[5] != "--root":
            return False
        try:
            if Path(arguments[6]).resolve() != self.root:
                return False
        except OSError:
            return False
        entrypoint = arguments[4]
        tail = arguments[7:]
        if entrypoint == "--child-probe":
            return len(tail) == 2 and tail[0] == "--nonce"
        if entrypoint == "--pytest-probe":
            return len(tail) == 2 and tail[0] == "--case" and tail[1] in {"catch", "xfail"}
        if entrypoint == "--compute-worker":
            if len(tail) != 4 or tail[0] != "--provider" or tail[2] != "--slow-ms":
                return False
            if tail[1] not in {"mock", "bge"}:
                return False
            try:
                float(tail[3])
            except ValueError:
                return False
            return True
        if entrypoint == "--pytest-runner":
            return len(tail) == 2 and tail[0] == "--kind" and tail[1] in {
                "guard",
                "baseline",
                "ac04",
                "ac05",
                "ac06",
                "ac07",
                "ac08",
                "ac09",
                "ac10",
                "ac11",
                "ac12",
                "ac13",
                "ac14",
                "ac15",
                "ac16",
                "ac17",
                "benchmark",
                "r05",
                "voice_answer_stream",
                "all",
            }
        if entrypoint == "--eval-script":
            if len(tail) < 1:
                return False
            script, *script_args = tail
            if script == "scripts/run_eval.py":
                return not script_args or script_args in (
                    ["--suite", "text_smoke"],
                    ["--suite", "rag_refactor"],
                    ["--suite", "voice_smoke"],
                    ["--suite", "structured_slices"],
                )
            if script == "scripts/validate_deployment.py":
                return script_args in (
                    ["--profile", "mock"],
                    ["--profile", "real"],
                )
            if script == "scripts/validate_knowledge_base.py":
                if len(script_args) != 2 or script_args[0] != "--config":
                    return False
                try:
                    Path(script_args[1]).resolve().relative_to(self.root / "pytest-basetemp")
                except ValueError:
                    return False
                return True
            if script == "scripts/_rag_faithfulness.py":
                if len(script_args) != 4 or script_args[:2] != ["--limit", "1"] or script_args[2] != "--output":
                    return False
                try:
                    Path(script_args[3]).resolve().relative_to(self.root)
                except ValueError:
                    return False
                return True
            return False
        if entrypoint == "--no-voice-eval":
            return not tail
        if entrypoint == "--app-cli":
            return bool(tail) and tail[0] == "--"
        if entrypoint in {"--feedback-query", "--feedback-rewrite"}:
            if len(tail) != 2 or tail[0] != "--job":
                return False
            try:
                Path(tail[1]).resolve().relative_to(self.root / "reports")
            except ValueError:
                return False
            return True
        return False

    def _base_child_command(self, entrypoint: str) -> list[str]:
        return [
            str(INTERPRETER),
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            entrypoint,
            "--root",
            str(self.root),
        ]

    def run_probe(self, nonce: str) -> subprocess.CompletedProcess[str]:
        command = self._base_child_command("--child-probe")
        command.extend(("--nonce", nonce))
        completed, _ = self._run_captured(command, timeout=30)
        return completed

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        command = self._base_child_command("--app-cli")
        command.append("--")
        command.extend(arguments)
        completed, _ = self._run_captured(command, timeout=90)
        return completed

    def run_pytest_probe(self, case: str) -> subprocess.CompletedProcess[str]:
        command = self._base_child_command("--pytest-probe")
        command.extend(("--case", case))
        completed, _ = self._run_captured(command, timeout=180)
        return completed

    def run_pytest(self, kind: str) -> subprocess.CompletedProcess[str]:
        command = self._base_child_command("--pytest-runner")
        command.extend(("--kind", kind))
        completed, raw = self._run_captured(command, timeout=600)
        self._write_pytest_report(kind, command, completed, raw)
        return completed

    def run_eval_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        command = self._base_child_command("--eval-script")
        command.extend(arguments)
        completed, _ = self._run_captured(command, timeout=90)
        return completed

    def run_no_voice_eval(self) -> subprocess.CompletedProcess[str]:
        command = self._base_child_command("--no-voice-eval")
        completed, _ = self._run_captured(command, timeout=90)
        return completed

    def run_feedback_query(self, job: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        return self._run_feedback_stage("--feedback-query", "query", job)

    def run_feedback_rewrite(self, job: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        return self._run_feedback_stage("--feedback-rewrite", "rewrite", job)

    def _run_feedback_stage(
        self,
        entrypoint: str,
        name: str,
        job: dict[str, Any],
    ) -> subprocess.CompletedProcess[str]:
        job_path = self.root / "reports" / f"feedback-{name}-job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        command = self._base_child_command(entrypoint)
        command.extend(("--job", str(job_path)))
        completed, _ = self._run_captured(command, timeout=90)
        return completed

    def _run_captured(
        self,
        command: list[str],
        *,
        timeout: int,
    ) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[bytes]]:
        raw = subprocess.run(
            command,
            cwd=self.root,
            env=self.child_env,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
        )
        stdout = self._decode_process_output(raw.stdout)
        stderr = self._decode_process_output(raw.stderr)
        return (
            subprocess.CompletedProcess(raw.args, raw.returncode, stdout, stderr),
            raw,
        )

    @staticmethod
    def _decode_process_output(data: bytes) -> str:
        for encoding in ("utf-8", locale.getpreferredencoding(False)):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def _write_pytest_report(
        self,
        kind: str,
        command: list[str],
        completed: subprocess.CompletedProcess[str],
        raw: subprocess.CompletedProcess[bytes],
    ) -> None:
        reports = self.root / "reports"
        stdout = completed.stdout.replace("\r\n", "\n").replace("\r", "\n")
        stderr = completed.stderr.replace("\r\n", "\n").replace("\r", "\n")
        (reports / f"{kind}.stdout.log").write_text(stdout, encoding="utf-8", newline="\n")
        (reports / f"{kind}.stderr.log").write_text(stderr, encoding="utf-8", newline="\n")
        (reports / f"{kind}.stdout.bin").write_bytes(raw.stdout)
        (reports / f"{kind}.stderr.bin").write_bytes(raw.stderr)
        cases_path = reports / f"{kind}-cases.json"
        cases = (
            json.loads(cases_path.read_text(encoding="utf-8"))
            if cases_path.is_file()
            else []
        )
        payload = {
            "kind": kind,
            "command": command,
            "cwd": str(self.root),
            "exit_code": completed.returncode,
            "cases": cases,
            "stdout_log": str(reports / f"{kind}.stdout.log"),
            "stderr_log": str(reports / f"{kind}.stderr.log"),
            "stdout_bytes": str(reports / f"{kind}.stdout.bin"),
            "stderr_bytes": str(reports / f"{kind}.stderr.bin"),
            "cases_path": str(cases_path),
            "git_head": BASELINE_HEAD,
            "git_head_source": "main-control-verified-baseline",
            "source_sha256": self._tree_sha256(WORKTREE / "src", {".py"}),
            "config_sha256": self._tree_sha256(WORKTREE / "configs", {".yaml", ".yml"}),
            "tests_sha256": self._tree_sha256(WORKTREE / "tests", {".py"}),
            "recorded_at_unix": time.time(),
        }
        (reports / f"ac02-{kind}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _tree_sha256(root: Path, suffixes: set[str]) -> str:
        digest = hashlib.sha256()
        for path in sorted(
            item
            for item in root.rglob("*")
            if item.is_file() and item.suffix in suffixes
        ):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(relative + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()


def current() -> OfflineEnvironment:
    if _ACTIVE is None:
        raise RuntimeError("AC02 offline environment is not active")
    return _ACTIVE


@contextmanager
def activate() -> Iterator[OfflineEnvironment]:
    global _ACTIVE
    if _ACTIVE is not None:
        yield _ACTIVE
        return
    previous_cwd = Path.cwd()
    environment = OfflineEnvironment.create()
    environment.install_guard()
    body_failed = False
    try:
        yield environment
    except BaseException:
        body_failed = True
        raise
    finally:
        unexpected = list(environment.guard.unexpected) if environment.guard else []
        if environment.guard is not None:
            environment.guard.restore()
        _ACTIVE = None
        os.chdir(previous_cwd)
        if unexpected and not _PYTEST_HOOK_ACTIVE and not body_failed:
            raise AssertionError(f"AC02 guard violations: {unexpected}")


def prepare_pytest(config) -> None:
    global _PYTEST_HOOK_ACTIVE, _SESSION_VIOLATIONS
    violations = getattr(config, "_ac02_guard_violations", None)
    if violations is None:
        violations = []
        setattr(config, "_ac02_guard_violations", violations)
    for event in _SESSION_VIOLATIONS:
        if event not in violations:
            violations.append(event)
    _SESSION_VIOLATIONS = violations
    _PYTEST_HOOK_ACTIVE = True
    module = sys.modules[__name__]
    if module not in config.pluginmanager.get_plugins():
        config.pluginmanager.register(module, "ac02_offline_runtime")


def _child_root(arguments: list[str]) -> tuple[OfflineEnvironment, list[str]]:
    if "--root" not in arguments:
        raise SystemExit("--root is required")
    index = arguments.index("--root")
    root = arguments[index + 1]
    remaining = arguments[:index] + arguments[index + 2 :]
    environment = OfflineEnvironment.load(root)
    environment.install_guard()
    return environment, remaining


def _install_import_paths() -> None:
    for path in (WORKTREE / "src", WORKTREE):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _bind_module_alias() -> None:
    import tests.helpers as helpers_package

    module = sys.modules[__name__]
    helpers_package.ac02_offline = module
    sys.modules["tests.helpers.ac02_offline"] = module


def _pytest_arguments(environment: OfflineEnvironment, kind: str) -> list[str]:
    if kind == "guard":
        selected = GUARD_TESTS
    elif kind == "r05":
        selected = R05_TESTS
    elif kind == "voice_answer_stream":
        selected = VOICE_ANSWER_STREAM_TESTS
    elif kind == "baseline":
        selected = BASELINE_TESTS
    elif kind == "ac05":
        selected = AC05_TESTS
    elif kind == "ac06":
        selected = AC06_TESTS
    elif kind == "ac07":
        selected = AC07_TESTS
    elif kind == "ac08":
        selected = AC08_TESTS
    elif kind == "ac09":
        selected = AC09_TESTS
    elif kind == "ac10":
        selected = AC10_TESTS
    elif kind == "ac11":
        selected = AC11_TESTS
    elif kind == "ac12":
        selected = AC12_TESTS
    elif kind == "ac13":
        selected = AC13_TESTS
    elif kind == "ac14":
        selected = AC14_TESTS
    elif kind == "ac15":
        selected = AC15_TESTS
    elif kind == "ac16":
        selected = AC16_TESTS
    elif kind == "ac17":
        selected = AC17_TESTS
    elif kind == "benchmark":
        selected = BENCHMARK_TESTS
    elif kind == "all":
        selected = ALL_TESTS
    elif kind == "ac04":
        selected = AC04_TESTS
    else:
        raise SystemExit(f"unknown pytest kind: {kind}")
    reports = environment.root / "reports"
    basetemp = environment.root / "pytest-basetemp" / kind
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    return [
        *(str(WORKTREE / path) for path in selected),
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_asyncio.plugin",
        "--basetemp",
        str(basetemp),
    ]


def _feedback_job(environment: OfflineEnvironment, arguments: list[str]) -> dict[str, Any]:
    if "--job" not in arguments:
        raise SystemExit("--job is required")
    job_path = Path(arguments[arguments.index("--job") + 1])
    job_path.resolve().relative_to(environment.root)
    return json.loads(job_path.read_text(encoding="utf-8"))


def _configure_feedback_logging() -> None:
    from observability.logging_config import configure_logging

    configure_logging()


def _run_feedback_query(environment: OfflineEnvironment, arguments: list[str]) -> int:
    _configure_feedback_logging()
    job = _feedback_job(environment, arguments)
    from app.api.schemas import TextQueryRequest
    from core.runtime_settings import RuntimeSettings
    from core.settings import load_settings
    from feedback.checkpoint_store import CheckpointStore
    from knowledge.ingestion.text_ingestor import TextIngestor
    from knowledge.retrieval_controller import RetrievalController
    from knowledge.schemas import ReviewStatus, SourceRecord
    from services.app_pipeline import AppPipeline
    from tests.helpers.knowledge_seed import seed_controller_chunks

    controller = RetrievalController.for_offline_test()
    source = SourceRecord(
        title="AC02 reviewed first-flight fixture",
        review_status=ReviewStatus.REVIEWED,
        authority_level="project_reviewed",
    )
    controller.source_registry.register_source(source)
    chunks = TextIngestor(controller.source_registry).ingest_text(
        source.source_id,
        job["evidence_text"],
        aircraft="C919",
        component="history",
        concept="首飞",
    )
    seed_controller_chunks(controller, chunks)
    pipeline = AppPipeline(
        retrieval_controller=controller,
        runtime_settings=RuntimeSettings.from_settings(load_settings("configs")),
        checkpoint_store=CheckpointStore(
            db_path=environment.root / "data" / "feedback.sqlite3"
        ),
    )
    try:
        response = pipeline.run_text_query(
            TextQueryRequest(
                query=job["query"],
                user_id=job["user_id"],
                session_id=job["session_id"],
                turn_id=job["turn_id"],
                run_id=job["run_id"],
            )
        )
    finally:
        pipeline.close()
    print(
        json.dumps(
            {"pid": os.getpid(), "response": response.to_dict()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if response.status == "ok" else 1


def _run_feedback_rewrite(environment: OfflineEnvironment, arguments: list[str]) -> int:
    _configure_feedback_logging()
    job = _feedback_job(environment, arguments)
    from core.contracts import FeedbackEvent
    from core.runtime_settings import RuntimeSettings
    from core.settings import load_settings
    from feedback.checkpoint_store import CheckpointStore
    from services.app_pipeline import AppPipeline

    store = CheckpointStore(db_path=environment.root / "data" / "feedback.sqlite3")
    pipeline = AppPipeline(
        runtime_settings=RuntimeSettings.from_settings(load_settings("configs")),
        checkpoint_store=store,
    )
    identity_rejected = False
    try:
        try:
            pipeline.get_feedback_checkpoint(
                job["checkpoint_id"],
                user_id="ac02-other-user",
                session_id=job["session_id"],
                turn_id=job["turn_id"],
            )
        except KeyError:
            identity_rejected = True
        result = pipeline.run_feedback(
            FeedbackEvent(
                run_id=job["run_id"],
                feedback_text="简单点",
                source="text",
            ),
            job["checkpoint_id"],
            user_id=job["user_id"],
            session_id=job["session_id"],
            turn_id=job["turn_id"],
        )
    finally:
        pipeline.close()
    print(
        json.dumps(
            {
                "identity_rejected": identity_rejected,
                "pid": os.getpid(),
                "feedback_intent": result.rewrite_plan.feedback_intent,
                "validation_passed": result.validation_passed,
                "validation_issues": [str(item) for item in result.validation_issues],
                "allowed_evidence_ids": sorted(result.evidence_lock.allowed_evidence_ids),
                "locked_claim_ids": sorted(result.evidence_lock.locked_claim_ids),
                "preserved_source_binding": result.evidence_lock.preserved_source_binding,
                "revised_evidence_refs": list(result.revised_answer.evidence_refs),
                "revised_source_bindings": {
                    binding.claim_id: list(binding.evidence_ids)
                    for binding in result.revised_answer.source_bindings
                },
                "short_answer": result.revised_answer.short_answer,
                "main_answer": result.revised_answer.main_answer,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.validation_passed else 1


def _dispatch_child(
    environment: OfflineEnvironment,
    entrypoint: str,
    remaining: list[str],
) -> int:
    if entrypoint == "--compute-worker":
        if "--provider" not in remaining or "--slow-ms" not in remaining:
            raise SystemExit("--provider and --slow-ms are required")
        provider = remaining[remaining.index("--provider") + 1]
        slow_ms = float(remaining[remaining.index("--slow-ms") + 1])
        if provider == "bge":
            architecture = os.environ.get("PROCESSOR_ARCHITECTURE", "")
            if not architecture:
                raise RuntimeError("Windows processor architecture is unavailable")
            # torch's platform.machine() otherwise runs Windows `ver` through
            # a shell, which the AC02 subprocess guard correctly rejects.
            platform.machine = lambda: architecture
        # -I isolates the child from pytest's sys.path (and any parent cwd
        # mutation).  Install the same approved project paths before importing
        # the worker; this helper owns that bootstrap for every child entry.
        _install_import_paths()
        from services.compute_worker import _serve

        return _serve(provider, slow_ms)

    if entrypoint == "--child-probe":
        if "--nonce" not in remaining:
            raise SystemExit("--nonce is required")
        nonce = remaining[remaining.index("--nonce") + 1]
        credential_names = {
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "NVIDIA_API_KEY",
            "OPENAI_API_KEY",
        }
        network_socket_blocked = False
        with environment.expect_block("network"):
            probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe_socket.connect(("192.0.2.1", 443))
            except Ac02GuardError:
                network_socket_blocked = True
            finally:
                probe_socket.close()

        network_urllib_blocked = False
        with environment.expect_block("network"):
            try:
                urllib.request.urlopen("http://192.0.2.1:81/ac02", timeout=0.2)
            except Ac02GuardError:
                network_urllib_blocked = True

        import httpx

        network_httpx_sync_blocked = False
        with environment.expect_block("network"):
            try:
                httpx.get("http://192.0.2.1:81/ac02", timeout=0.2)
            except Ac02GuardError:
                network_httpx_sync_blocked = True

        async def async_httpx_request() -> None:
            async with httpx.AsyncClient(timeout=0.2) as client:
                await client.get("http://192.0.2.1:81/ac02")

        network_httpx_async_blocked = False
        with environment.expect_block("network"):
            try:
                asyncio.run(async_httpx_request())
            except Ac02GuardError:
                network_httpx_async_blocked = True
            except BaseExceptionGroup as error:
                if not guard_errors_only(error):
                    raise
                network_httpx_async_blocked = True

        network_guard_active = all(
            (
                network_socket_blocked,
                network_urllib_blocked,
                network_httpx_sync_blocked,
                network_httpx_async_blocked,
            )
        )
        probe_database = environment.root.parent / f"{environment.root.name}-probe.sqlite3"
        sqlite_guard_active = False
        with environment.expect_block("sqlite"):
            try:
                sqlite3.connect(probe_database)
            except Ac02GuardError:
                sqlite_guard_active = True
        if probe_database.exists():
            probe_database.unlink()
        receipt = {
            "guard_active": bool(environment.guard and environment.guard.installed),
            "network_guard_active": network_guard_active,
            "network_socket_blocked": network_socket_blocked,
            "network_urllib_blocked": network_urllib_blocked,
            "network_httpx_sync_blocked": network_httpx_sync_blocked,
            "network_httpx_async_blocked": network_httpx_async_blocked,
            "sqlite_guard_active": sqlite_guard_active,
            "nonce": nonce,
            "entrypoint": "ac02-offline-child",
            "credential_env_present": bool(credential_names & set(os.environ)),
            "proxy_env_present": bool(
                {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
                & set(os.environ)
            ),
        }
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0

    _install_import_paths()
    _bind_module_alias()
    if entrypoint == "--eval-script":
        if not remaining:
            raise SystemExit("--eval-script requires a script")
        script, *script_arguments = remaining
        if (
            script == "scripts/run_eval.py"
            and script_arguments == ["--suite", "voice_smoke"]
            and environment.guard is not None
        ):
            environment.guard.allow_loopback_rebind = True
        import importlib

        module_name = {
            "scripts/run_eval.py": "scripts.run_eval",
            "scripts/validate_deployment.py": "scripts.validate_deployment",
            "scripts/validate_knowledge_base.py": "scripts.validate_knowledge_base",
            "scripts/_rag_faithfulness.py": "scripts._rag_faithfulness",
        }.get(script)
        if module_name is None:
            raise SystemExit(f"unsupported eval script: {script}")
        return int(importlib.import_module(module_name).main(script_arguments))
    if entrypoint == "--no-voice-eval":
        import builtins

        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in {"voice", "input.voice_query_normalizer"} or name.startswith("voice."):
                raise AssertionError(f"unexpected voice import: {name}")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import
        from scripts import run_eval

        return run_eval.main(["--suite", "text_smoke"])
    if entrypoint == "--pytest-probe":
        if len(remaining) != 2 or remaining[0] != "--case":
            raise SystemExit("--case catch|xfail is required")
        return _run_sticky_probe(environment, remaining[1])
    if entrypoint == "--feedback-query":
        return _run_feedback_query(environment, remaining)
    if entrypoint == "--feedback-rewrite":
        return _run_feedback_rewrite(environment, remaining)
    if entrypoint == "--app-cli":
        from app.cli import main as app_main

        if remaining and remaining[0] == "--":
            remaining = remaining[1:]
        return app_main(remaining)

    if entrypoint == "--pytest-runner":
        if "--kind" not in remaining:
            raise SystemExit("--kind is required")
        kind = remaining[remaining.index("--kind") + 1]
        environment.pytest_kind = kind
        import pytest

        return int(pytest.main(_pytest_arguments(environment, kind), plugins=[sys.modules[__name__]]))

    raise SystemExit(f"unknown entrypoint: {entrypoint}")


_STICKY_PROBE_SOURCE = '''\
from __future__ import annotations

import subprocess
import sys

import pytest

from tests.helpers import ac02_offline


{decorator}
def test_{case}(request) -> None:
    ac02_offline.prepare_pytest(request.config)
    with ac02_offline.activate():
        try:
            subprocess.run(
                [sys.executable, "-I", "-B", "-c", "print('ac02-forbidden')"],
                check=False,
                capture_output=True,
                text=True,
            )
        except ac02_offline.Ac02GuardError:
            pass
{tail}
'''


def _run_sticky_probe(environment: OfflineEnvironment, case: str) -> int:
    global _ACTIVE, _PYTEST_HOOK_ACTIVE, _SESSION_VIOLATIONS
    if case not in {"catch", "xfail"}:
        raise SystemExit(f"unknown probe case: {case}")
    if environment.guard is not None:
        environment.guard.restore()
    _ACTIVE = None
    _PYTEST_HOOK_ACTIVE = False
    _SESSION_VIOLATIONS = []
    probe_dir = environment.root / "reports" / "pytest-probe" / case
    probe_dir.mkdir(parents=True, exist_ok=True)
    test_path = probe_dir / "test_sticky_isolation.py"
    decorator = "@pytest.mark.xfail(strict=False)" if case == "xfail" else ""
    tail = "    assert False" if case == "xfail" else ""
    test_path.write_text(
        _STICKY_PROBE_SOURCE.format(decorator=decorator, case=case, tail=tail),
        encoding="utf-8",
        newline="\n",
    )

    class ProbeResults:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def pytest_runtest_logreport(self, report) -> None:
            if report.when == "call":
                self.calls.append(
                    {
                        "outcome": report.outcome,
                        "wasxfail": getattr(report, "wasxfail", None) is not None,
                    }
                )

    results = ProbeResults()
    import pytest

    exit_code = int(
        pytest.main(
            [
                str(test_path),
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(probe_dir / "basetemp"),
            ],
            plugins=[sys.modules[__name__], results],
        )
    )
    print(
        json.dumps(
            {
                "case": case,
                "exit_code": exit_code,
                "calls": results.calls,
                "violations": _guard_violations(environment),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return exit_code


def _guard_violations(environment: OfflineEnvironment | None = None) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if environment is not None and environment.guard is not None:
        events.extend(environment.guard.unexpected)
    events.extend(_SESSION_VIOLATIONS)
    unique: list[dict[str, str]] = []
    for event in events:
        if event not in unique:
            unique.append(event)
    return unique


def _run_child(entrypoint: str, arguments: list[str]) -> int:
    environment, remaining = _child_root(arguments)
    exit_code = _dispatch_child(environment, entrypoint, remaining)
    violations = _guard_violations(environment)
    if violations:
        print(
            f"AC02 guard violation: {violations}",
            file=sys.stderr,
        )
        return 1
    return exit_code


def _main(arguments: list[str]) -> int:
    if not arguments:
        print(
            "usage: ac02_offline.py --guard-tests|--baseline|--ac04-tests|--ac05-tests|--ac06-tests|--ac07-tests|--ac08-tests|--ac09-tests|--ac10-tests|--ac11-tests|--ac12-tests|--ac13-tests|--ac14-tests|--ac15-tests|--ac16-tests|--ac17-tests|--benchmark-tests|--r05-tests|--voice-answer-stream-tests|--all-tests|--r06-baseline|--r06-pilot|--r06-performance|--r12-baseline|--r12-pilot|--r12-performance|--matrix-cache-baseline|--matrix-cache-micro|--matrix-cache-performance|--r07-eval|--r09-eval|internal-entrypoint",
            file=sys.stderr,
        )
        return 2
    entrypoint = arguments[0]
    if entrypoint == "--r05-tests" and len(arguments) != 1:
        print("--r05-tests accepts no additional arguments", file=sys.stderr)
        return 2
    if entrypoint == "--voice-answer-stream-tests" and len(arguments) != 1:
        print("--voice-answer-stream-tests accepts no additional arguments", file=sys.stderr)
        return 2
    if entrypoint in _CHILD_ENTRYPOINTS:
        return _run_child(entrypoint, arguments[1:])
    if entrypoint in {
        "--r06-baseline",
        "--r06-pilot",
        "--r06-performance",
        "--r12-baseline",
        "--r12-pilot",
        "--r12-performance",
        "--matrix-cache-baseline",
        "--matrix-cache-micro",
        "--matrix-cache-performance",
    } and len(arguments) == 1:
        environment = OfflineEnvironment.create()
        environment.install_guard()
        _install_import_paths()
        from scripts.agent_benchmark.compare_retrieval_channels import (
            run_baseline,
            run_performance,
            run_pilot,
            run_r12_baseline,
            run_r12_pilot,
            run_r12_performance,
            run_matrix_cache_baseline,
            run_matrix_cache_micro,
            run_matrix_cache_performance,
        )

        result = {
            "--r06-baseline": run_baseline,
            "--r06-pilot": run_pilot,
            "--r06-performance": run_performance,
            "--r12-baseline": run_r12_baseline,
            "--r12-pilot": run_r12_pilot,
            "--r12-performance": run_r12_performance,
            "--matrix-cache-baseline": run_matrix_cache_baseline,
            "--matrix-cache-micro": run_matrix_cache_micro,
            "--matrix-cache-performance": run_matrix_cache_performance,
        }[entrypoint](environment)
        violations = _guard_violations(environment)
        if violations:
            print(f"AC02 guard violation: {violations}", file=sys.stderr)
            return 1
        return result
    if entrypoint == "--r07-eval" and len(arguments) == 1:
        environment = OfflineEnvironment.create()
        environment.install_guard()
        print(f"AC02 offline root: {environment.root}", flush=True)
        completed = environment.run_eval_script(
            "scripts/run_eval.py", "--suite", "structured_slices"
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        violations = _guard_violations(environment)
        if violations:
            print(f"AC02 guard violation: {violations}", file=sys.stderr)
            return 1
        print(f"AC02 r07 eval exit code: {completed.returncode}")
        return completed.returncode
    if entrypoint == "--r09-eval" and len(arguments) == 1:
        environment = OfflineEnvironment.create()
        environment.install_guard()
        _install_import_paths()
        from scripts.agent_benchmark.snapshot_structured_slices import run_snapshot_eval

        result = run_snapshot_eval(environment)
        violations = _guard_violations(environment)
        if violations:
            print(f"AC02 guard violation: {violations}", file=sys.stderr)
            return 1
        print(f"AC02 r09 eval exit code: {result}")
        return result
    if entrypoint not in {"--guard-tests", "--baseline", "--ac04-tests", "--ac05-tests", "--ac06-tests", "--ac07-tests", "--ac08-tests", "--ac09-tests", "--ac10-tests", "--ac11-tests", "--ac12-tests", "--ac13-tests", "--ac14-tests", "--ac15-tests", "--ac16-tests", "--ac17-tests", "--benchmark-tests", "--r05-tests", "--voice-answer-stream-tests", "--all-tests"}:
        print(f"unknown option: {entrypoint}", file=sys.stderr)
        return 2
    kind = {
        "--guard-tests": "guard",
        "--baseline": "baseline",
        "--ac04-tests": "ac04",
        "--ac05-tests": "ac05",
        "--ac06-tests": "ac06",
        "--ac07-tests": "ac07",
        "--ac08-tests": "ac08",
        "--ac09-tests": "ac09",
        "--ac10-tests": "ac10",
        "--ac11-tests": "ac11",
        "--ac12-tests": "ac12",
        "--ac13-tests": "ac13",
        "--ac14-tests": "ac14",
        "--ac15-tests": "ac15",
        "--ac16-tests": "ac16",
        "--ac17-tests": "ac17",
        "--benchmark-tests": "benchmark",
        "--r05-tests": "r05",
        "--voice-answer-stream-tests": "voice_answer_stream",
        "--all-tests": "all",
    }[entrypoint]
    environment = OfflineEnvironment.create()
    environment.install_guard()
    print(f"AC02 offline root: {environment.root}", flush=True)
    completed = environment.run_pytest(kind)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    print(f"AC02 {kind} report: {environment.root / 'reports' / f'ac02-{kind}.json'}")
    print(f"AC02 {kind} exit code: {completed.returncode}")
    return completed.returncode


def pytest_sessionfinish(session, exitstatus) -> None:
    global _PYTEST_HOOK_ACTIVE
    _PYTEST_HOOK_ACTIVE = False
    environment = _ACTIVE
    if environment is not None and environment.guard is not None:
        cases_path = environment.root / "reports" / f"{environment.pytest_kind}-cases.json"
        cases_path.write_text(
            json.dumps(environment.pytest_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    violations = _guard_violations(environment)
    if violations:
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line("AC02 unexpected guard events:")
            for event in violations:
                terminal.write_line(f"  {event}")
        if not session.exitstatus:
            session.exitstatus = 1


def pytest_runtest_logreport(report) -> None:
    if _ACTIVE is None or _ACTIVE.pytest_kind not in {"guard", "baseline", "ac04", "ac05", "ac06", "ac07", "ac08", "ac09", "ac10", "ac11", "ac12", "ac13", "ac14", "ac15", "ac16", "ac17", "benchmark", "r05", "voice_answer_stream", "all"}:
        return
    detail = ""
    if report.outcome != "passed" and report.longrepr is not None:
        detail = str(report.longrepr)[:4000]
    _ACTIVE.pytest_results.append(
        {
            "nodeid": report.nodeid,
            "phase": report.when,
            "outcome": report.outcome,
            "duration_seconds": report.duration,
            "detail": detail,
        }
    )


_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_SOCKET_BIND = socket.socket.bind
_ORIGINAL_SOCKET_CLOSE = socket.socket.close
_ORIGINAL_SENDTO = socket.socket.sendto
_ORIGINAL_SSL_CONNECT = ssl.SSLSocket.connect
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect
_ORIGINAL_SQLITE_DBAPI_CONNECT = sqlite3.dbapi2.connect
_ORIGINAL_SELECTOR_CONNECT = asyncio.selector_events.BaseSelectorEventLoop.sock_connect
_ORIGINAL_SELECTOR_SENDTO = asyncio.selector_events.BaseSelectorEventLoop.sock_sendto
_ORIGINAL_PROACTOR_CONNECT = asyncio.proactor_events.BaseProactorEventLoop.sock_connect
_ORIGINAL_PROACTOR_SENDTO = asyncio.proactor_events.BaseProactorEventLoop.sock_sendto


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
