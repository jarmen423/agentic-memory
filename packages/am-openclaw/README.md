# am-openclaw

OpenClaw integration scaffold for Agentic Memory.

This package exists so the OpenClaw wave has a real workspace target from the
start:

- future plugin code lives here
- the package can be compiled independently with `tsc`
- setup helpers can grow without mixing into the main backend or desktop shell

## What belongs here

- OpenClaw package metadata
- bootstrap/config helpers for the magic setup path
- typed contracts for memory and context-engine wiring
- future plugin entrypoints once the package shape settles

## Current status

This is intentionally minimal. The next wave should add the real OpenClaw plugin
runtime and connect it to the backend routes already added elsewhere in the
repository.
