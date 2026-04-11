"""Unit tests for am-proxy CLI entry point."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, patch

import pytest

from am_proxy.cli import (
    _build_parser,
    _cmd_setup,
    _default_codex_child_args,
    _normalize_child_args,
    main,
)


# --- Argument parser ---

def test_parser_requires_agent_for_run() -> None:
    """--agent is required for the run path."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["--project", "p1"])
    assert args.agent is None


def test_parser_captures_agent_args() -> None:
    """Unknown flag-style args after known flags are captured in remaining."""
    parser = _build_parser()
    args, remaining = parser.parse_known_args(
        ["--agent", "claude", "--project", "proj", "--verbose"]
    )
    assert "--verbose" in remaining


def test_parser_passes_resume_and_session_name() -> None:
    """Positional args (e.g. codex resume <name>) are not mistaken for subcommands."""
    parser = _build_parser()
    args, remaining = parser.parse_known_args(
        ["--agent", "codex", "--project", "proj", "resume", "Radiology"]
    )
    assert args.agent == "codex"
    assert remaining == ["resume", "Radiology"]


def test_parser_passes_double_dash_and_flags_to_child() -> None:
    """``--`` and following tokens remain in ``remaining`` for the child process."""
    parser = _build_parser()
    args, remaining = parser.parse_known_args(
        ["--agent", "codex", "--project", "p", "--", "--acp"]
    )
    assert remaining == ["--", "--acp"]


def test_parser_app_server_listen_passthrough() -> None:
    parser = _build_parser()
    _, remaining = parser.parse_known_args(
        [
            "--agent",
            "codex",
            "--project",
            "p",
            "app-server",
            "--listen",
            "stdio://",
        ]
    )
    assert remaining == ["app-server", "--listen", "stdio://"]


def test_parser_debug_flag() -> None:
    """--debug flag sets debug=True."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["--agent", "claude", "--debug"])
    assert args.debug is True


def test_parser_endpoint_override() -> None:
    """--endpoint override is captured."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["--agent", "claude", "--endpoint", "http://myserver:8080"])
    assert args.endpoint == "http://myserver:8080"


def test_parser_api_key_override() -> None:
    """--api-key override is captured as api_key attribute."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["--agent", "claude", "--api-key", "secret-token"])
    assert getattr(args, "api_key", None) == "secret-token"


def test_parser_project_override() -> None:
    """--project override is captured."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["--agent", "claude", "--project", "my-project"])
    assert args.project == "my-project"


def test_default_codex_child_args_app_server_when_empty() -> None:
    assert _default_codex_child_args([]) == ["app-server"]


def test_default_codex_child_args_preserves_explicit() -> None:
    assert _default_codex_child_args(["resume", "--last"]) == ["resume", "--last"]


def test_normalize_child_args_strips_double_dash_separator() -> None:
    assert _normalize_child_args(["--", "app-server", "--listen", "stdio://"]) == [
        "app-server",
        "--listen",
        "stdio://",
    ]


def test_normalize_child_args_preserves_regular_passthrough() -> None:
    assert _normalize_child_args(["resume", "Radiology"]) == ["resume", "Radiology"]


# --- setup subcommand ---

def test_cmd_setup_no_agents_found(capsys) -> None:
    """setup prints 'no agents' message when none detected."""
    with patch("am_proxy.cli.detect_installed_agents", return_value=[]):
        _cmd_setup()
    captured = capsys.readouterr()
    assert "No supported agents found" in captured.out
    assert "claude" in captured.out


def test_cmd_setup_detected_agent_prints_snippet(capsys) -> None:
    """setup prints editor config snippet for each detected agent."""
    with patch("am_proxy.cli.detect_installed_agents", return_value=["claude", "codex"]):
        _cmd_setup()
    captured = capsys.readouterr()
    assert "Claude detected" in captured.out
    assert "am-proxy --agent claude" in captured.out
    assert "Codex detected" in captured.out
    assert "am-proxy --agent codex" in captured.out


def test_cmd_setup_single_agent(capsys) -> None:
    """setup with single detected agent prints its snippet."""
    with patch("am_proxy.cli.detect_installed_agents", return_value=["gemini"]):
        _cmd_setup()
    captured = capsys.readouterr()
    assert "Gemini detected" in captured.out
    assert "am-proxy --agent gemini" in captured.out


# --- Windows event loop policy ---

def _make_asyncio_run_mock(return_value: int = 0):
    """Create an asyncio.run side_effect that closes the coroutine and returns value."""

    def fake_run(coro):
        coro.close()
        return return_value

    return fake_run


def test_windows_policy_set_on_win32() -> None:
    """WindowsProactorEventLoopPolicy is set when platform is win32."""
    with (
        patch.object(sys, "platform", "win32"),
        patch("asyncio.set_event_loop_policy") as mock_set_policy,
        patch("asyncio.run", side_effect=_make_asyncio_run_mock(0)),
        patch("sys.exit"),
        patch("sys.argv", ["am-proxy", "--agent", "claude"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="claude"),
        patch("am_proxy.cli._run_proxy", AsyncMock(return_value=0)),
    ):
        main()
        mock_set_policy.assert_called_once()
        call_arg = mock_set_policy.call_args[0][0]
        assert type(call_arg).__name__ == "WindowsProactorEventLoopPolicy"


def test_windows_policy_not_set_on_linux() -> None:
    """WindowsProactorEventLoopPolicy is NOT set on linux."""
    with (
        patch.object(sys, "platform", "linux"),
        patch("asyncio.set_event_loop_policy") as mock_set_policy,
        patch("asyncio.run", side_effect=_make_asyncio_run_mock(0)),
        patch("sys.exit"),
        patch("sys.argv", ["am-proxy", "--agent", "claude"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="claude"),
        patch("am_proxy.cli._run_proxy", AsyncMock(return_value=0)),
    ):
        main()
        mock_set_policy.assert_not_called()


# --- main() exit code propagation ---

def test_main_exits_with_subprocess_exit_code() -> None:
    """main() calls sys.exit() with the subprocess exit code."""
    with (
        patch("asyncio.run", side_effect=_make_asyncio_run_mock(42)),
        patch("sys.exit") as mock_exit,
        patch("sys.argv", ["am-proxy", "--agent", "claude"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="claude"),
        patch("am_proxy.cli._run_proxy", AsyncMock(return_value=0)),
    ):
        main()
        mock_exit.assert_called_once_with(42)


def test_main_setup_does_not_call_sys_exit() -> None:
    """setup subcommand returns cleanly without sys.exit."""
    with (
        patch("am_proxy.cli.detect_installed_agents", return_value=[]),
        patch("asyncio.run") as mock_run,
        patch("sys.exit") as mock_exit,
        patch("sys.argv", ["am-proxy", "setup"]),
    ):
        main()
        mock_run.assert_not_called()
        mock_exit.assert_not_called()


def test_main_setup_with_agents_does_not_call_sys_exit() -> None:
    """setup subcommand with detected agents still returns without sys.exit."""
    with (
        patch("am_proxy.cli.detect_installed_agents", return_value=["claude"]),
        patch("asyncio.run") as mock_run,
        patch("sys.exit") as mock_exit,
        patch("sys.argv", ["am-proxy", "setup"]),
    ):
        main()
        mock_run.assert_not_called()
        mock_exit.assert_not_called()


def test_main_exit_code_zero() -> None:
    """main() propagates exit code 0 from successful subprocess."""
    with (
        patch("asyncio.run", side_effect=_make_asyncio_run_mock(0)),
        patch("sys.exit") as mock_exit,
        patch("sys.argv", ["am-proxy", "--agent", "claude"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="claude"),
        patch("am_proxy.cli._run_proxy", AsyncMock(return_value=0)),
    ):
        main()
        mock_exit.assert_called_once_with(0)


def test_main_exit_code_nonzero_error() -> None:
    """main() propagates nonzero exit code from failed subprocess."""
    with (
        patch("asyncio.run", side_effect=_make_asyncio_run_mock(1)),
        patch("sys.exit") as mock_exit,
        patch("sys.argv", ["am-proxy", "--agent", "claude"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="claude"),
        patch("am_proxy.cli._run_proxy", AsyncMock(return_value=0)),
    ):
        main()
        mock_exit.assert_called_once_with(1)


def test_main_passes_agent_args_through() -> None:
    """Extra args after flags are passed to the proxy (e.g. positional for child)."""
    run_proxy = AsyncMock(return_value=0)

    with (
        patch("asyncio.run", side_effect=asyncio.run),
        patch("sys.exit"),
        patch("sys.argv", ["am-proxy", "--agent", "claude", "--project", "p1", "some-file.py"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="claude"),
        patch("am_proxy.cli._run_proxy", run_proxy),
    ):
        main()

    run_proxy.assert_called_once()
    assert run_proxy.call_args.kwargs["agent_args"] == ["some-file.py"]


def test_main_codex_defaults_app_server() -> None:
    """Codex with no extra argv gets default app-server child args."""
    run_proxy = AsyncMock(return_value=0)

    with (
        patch("asyncio.run", side_effect=asyncio.run),
        patch("sys.exit"),
        patch("sys.argv", ["am-proxy", "--agent", "codex", "--project", "p1"]),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="codex"),
        patch("am_proxy.cli._run_proxy", run_proxy),
    ):
        main()

    assert run_proxy.call_args.kwargs["agent_args"] == ["app-server"]


def test_main_strips_double_dash_before_child_args() -> None:
    """Leading separator is not forwarded to Codex."""
    run_proxy = AsyncMock(return_value=0)

    with (
        patch("asyncio.run", side_effect=asyncio.run),
        patch("sys.exit"),
        patch(
            "sys.argv",
            [
                "am-proxy",
                "--agent",
                "codex",
                "--project",
                "p1",
                "--",
                "app-server",
                "--listen",
                "stdio://",
            ],
        ),
        patch("am_proxy.cli.resolved_binary_for_agent", return_value="codex"),
        patch("am_proxy.cli._run_proxy", run_proxy),
    ):
        main()

    assert run_proxy.call_args.kwargs["agent_args"] == ["app-server", "--listen", "stdio://"]


def test_main_no_agent_error() -> None:
    """main() exits with error when --agent is not provided."""
    with (
        patch("sys.argv", ["am-proxy"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code != 0


def test_cmd_setup_calls_detect_installed_agents() -> None:
    """_cmd_setup calls detect_installed_agents."""
    with patch("am_proxy.cli.detect_installed_agents", return_value=[]) as det:
        _cmd_setup()
        det.assert_called_once()
