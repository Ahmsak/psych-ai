# Psych AI Architecture

## MISSION
- The system assists the psychologist, not replaces the psychologist.

## Core components

- App
- UI
- Orchestrator. The Orchestrator is the only component that coordinates other modules.
Modules never communicate directly with each other.
- Session
- Memory
- Agents
- Validator

## Future

- Multi-agent system
- Long-term memory
- Episode model
- Constitution
- Narrative agent

## Principles

- One responsibility per module.
- Agents never communicate directly.
- All communication goes through the Orchestrator.
- Ethics are centralized.
- The Constitution is independent from the LLM.
- Memory stores facts, not conclusions.