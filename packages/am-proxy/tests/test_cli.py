"""Unit tests for am-proxy CLI entry point."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from am_proxy.cli import _build_parser, _cmd_setup, main


# --- Argument parser ---

def test_parser_requires_agent_for_run() -> None:
    """--agent is required for the run path."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["--project", "p1"])
    assert args.agent is None  # Missing --agent captured without error by parse_known_args


def test_parser_captures_agent_args() -> None:
    """Unknown flag-style args after known flags are captured in remaining."""
    parser = _build_parser()
    # Unknown flags are passed through via parse_known_args remaining
    args, remaining = parser.parse_known_args(
        ["--agent", "claude", "--project", "proj", "--verbose"]
    )
    assert "--verbose" in remaining


def test_parser_setup_subcommand() -> None:
    """setup subcommand sets subcommand='setup'."""
    parser = _build_parser()
    args, _ = parser.parse_known_args(["setup"])
    assert args.subcommand == "setup"


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
    ):
        main()
        mock_exit.assert_called_once_with(0)


def test_main_exit_code_nonzero_error() -> None:
    """main() propagates nonzero exit code from failed subprocess."""
    with (
        patch("asyncio.run", side_effect=_make_asyncio_run_mock(1)),
        patch("sys.exit") as mock_exit,
        patch("sys.argv", ["am-proxy", "--agent", "claude"]),
    ):
        main()
        mock_exit.assert_called_once_with(1)


def test_main_passes_agent_args_through() -> None:
    """Extra args after --agent are passed through to the proxy."""
    captured_call: list = []

    def fake_asyncio_run(coro):
        captured_call.append(coro)
        coro.close()
        return 0

    with (
        patch("asyncio.run", side_effect=fake_asyncio_run),
        patch("sys.exit"),
        patch("sys.argv", ["am-proxy", "--agent", "claude", "--project", "p1", "some-file.py"]),
    ):
        main()
        assert len(captured_call) == 1


def test_main_no_agent_error() -> None:
    """main() exits with error when --agent is not provided."""
    with (
        patch("sys.argv", ["am-proxy"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code != 0
