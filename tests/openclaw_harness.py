"""Helpers for OpenClaw-style shared memory verification tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenClawIdentity:
    """Identity tuple for a single OpenClaw device/agent/session."""

    workspace_id: str
    device_id: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class OpenClawTurn:
    """Synthetic OpenClaw turn payload used by stress tests."""

    identity: OpenClawIdentity
    turn_index: int
    content: str

    def event_details(self) -> dict[str, object]:
        """Return a backend-friendly event payload."""
        return {
            "workspace_id": self.identity.workspace_id,
            "device_id": self.identity.device_id,
            "agent_id": self.identity.agent_id,
            "session_id": self.identity.session_id,
            "turn_index": self.turn_index,
            "content": self.content,
        }

    def repo_metadata(self) -> dict[str, object]:
        """Return metadata suitable for repo/integration records."""
        return {
            "workspace_id": self.identity.workspace_id,
            "device_id": self.identity.device_id,
            "agent_id": self.identity.agent_id,
            "session_id": self.identity.session_id,
        }


def build_openclaw_workload(
    *,
    workspace_id: str,
    devices: int = 3,
    agents_per_device: int = 4,
    turns_per_agent: int = 5,
) -> list[OpenClawTurn]:
    """Generate a deterministic multi-device, multi-agent workload."""
    turns: list[OpenClawTurn] = []
    turn_index = 0
    for device_index in range(devices):
        device_id = f"device-{device_index + 1}"
        for agent_index in range(agents_per_device):
            agent_id = f"agent-{device_index + 1}-{agent_index + 1}"
            session_id = f"{workspace_id}:{device_id}:{agent_id}"
            identity = OpenClawIdentity(
                workspace_id=workspace_id,
                device_id=device_id,
                agent_id=agent_id,
                session_id=session_id,
            )
            for local_turn in range(turns_per_agent):
                turns.append(
                    OpenClawTurn(
                        identity=identity,
                        turn_index=turn_index,
                        content=f"{workspace_id} {device_id} {agent_id} turn {local_turn + 1}",
                    )
                )
                turn_index += 1
    return turns
