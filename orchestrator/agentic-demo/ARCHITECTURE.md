<div align="center">

# 🏗️ System Design & Architecture

### Agentic AI Demo — Technical Architecture Document

</div>

---

## 📑 Table of Contents

- [1. System Overview](#1-system-overview)
- [2. High-Level Architecture](#2-high-level-architecture)
- [3. Component Architecture](#3-component-architecture)
- [4. Data Flow — Sequence Diagram](#4-data-flow--sequence-diagram)
- [5. State Machine — Automata Diagram](#5-state-machine--automata-diagram)
- [6. Module Breakdown](#6-module-breakdown)
- [7. Class & Type Diagram](#7-class--type-diagram)
- [8. Deployment Architecture](#8-deployment-architecture)
- [9. Design Decisions](#9-design-decisions)

---

## 1. System Overview

The **Agentic AI Demo** is a goal-driven autonomous agent system that follows a **plan → execute → aggregate** paradigm. A user provides a high-level goal, and the system:

1. **Plans** — Decomposes the goal into actionable sub-tasks using an LLM.
2. **Executes** — Runs tool-augmented actions (e.g., calculations) on the planned steps.
3. **Aggregates** — Combines the plan and tool outputs into a final structured result.

The entire pipeline is orchestrated as a **directed acyclic graph (DAG)** using LangGraph, with each processing stage represented as a node in the graph.

---

## 2. High-Level Architecture

```mermaid
graph TB
    subgraph User Layer
        A["👤 User"]
    end

    subgraph Presentation Layer
        B["🖥️ Streamlit Web UI<br/><i>app.py</i>"]
        C["⌨️ CLI Interface<br/><i>main.py</i>"]
    end

    subgraph Orchestration Layer
        D["🔗 LangGraph State Graph<br/><i>graph/agent_graph.py</i>"]
    end

    subgraph Agent Layer
        E["🧠 Planner Agent<br/><i>agents/planner_agent.py</i>"]
    end

    subgraph Tool Layer
        F["🧮 Calculator Tool<br/><i>tools/calculator_tool.py</i>"]
    end

    subgraph Prompt Layer
        G["📝 Planner Prompt Template<br/><i>prompts/planner_prompt.py</i>"]
    end

    subgraph Infrastructure Layer
        H["⚙️ LLM Loader<br/><i>utils/llm_loader.py</i>"]
        I["🤖 Ollama Server<br/><i>Qwen3:8b Model</i>"]
    end

    A -->|"enters goal"| B
    A -->|"runs script"| C
    B -->|"invokes"| D
    C -->|"invokes"| D
    D -->|"calls"| E
    D -->|"calls"| F
    E -->|"uses"| G
    E -->|"loads"| H
    H -->|"HTTP API"| I

    style A fill:#4A90D9,stroke:#2C5F8A,color:#fff
    style B fill:#FF4B4B,stroke:#CC3333,color:#fff
    style C fill:#6C757D,stroke:#495057,color:#fff
    style D fill:#FF6F00,stroke:#CC5800,color:#fff
    style E fill:#28A745,stroke:#1E7E34,color:#fff
    style F fill:#FFC107,stroke:#D39E00,color:#000
    style G fill:#17A2B8,stroke:#117A8B,color:#fff
    style H fill:#6F42C1,stroke:#5A32A3,color:#fff
    style I fill:#000000,stroke:#333333,color:#fff
```

---

## 3. Component Architecture

```mermaid
graph LR
    subgraph "Entry Points"
        APP["app.py<br/>Streamlit UI"]
        MAIN["main.py<br/>CLI Runner"]
    end

    subgraph "Graph Engine"
        GRAPH["agent_graph.py"]
        STATE["AgentState<br/>(TypedDict)"]
        PN["planner_node()"]
        TN["tool_node()"]
        FN["final_node()"]
    end

    subgraph "Agents"
        PA["planner_agent.py<br/>create_plan()"]
    end

    subgraph "Prompts"
        PP["planner_prompt.py<br/>PLANNER_PROMPT"]
    end

    subgraph "Tools"
        CT["calculator_tool.py<br/>@tool calculator()"]
    end

    subgraph "Utilities"
        LLM["llm_loader.py<br/>load_llm()"]
    end

    subgraph "External"
        OLLAMA["Ollama Server<br/>localhost:11434"]
    end

    APP --> GRAPH
    MAIN --> GRAPH
    GRAPH --> STATE
    GRAPH --> PN
    GRAPH --> TN
    GRAPH --> FN
    PN --> PA
    PA --> PP
    PA --> LLM
    TN --> CT
    LLM --> OLLAMA

    style APP fill:#FF4B4B,color:#fff
    style MAIN fill:#6C757D,color:#fff
    style GRAPH fill:#FF6F00,color:#fff
    style STATE fill:#FFB74D,color:#000
    style PN fill:#81C784,color:#000
    style TN fill:#FFF176,color:#000
    style FN fill:#90CAF9,color:#000
    style PA fill:#28A745,color:#fff
    style PP fill:#17A2B8,color:#fff
    style CT fill:#FFC107,color:#000
    style LLM fill:#6F42C1,color:#fff
    style OLLAMA fill:#000,color:#fff
```

---

## 4. Data Flow — Sequence Diagram

This sequence diagram shows the complete lifecycle of a user request flowing through all system components.

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit UI<br/>(app.py)
    participant Graph as LangGraph Engine<br/>(agent_graph.py)
    participant Planner as Planner Node
    participant Agent as Planner Agent<br/>(planner_agent.py)
    participant Prompt as Prompt Template<br/>(planner_prompt.py)
    participant Loader as LLM Loader<br/>(llm_loader.py)
    participant Ollama as Ollama Server<br/>(Qwen3:8b)
    participant Tool as Tool Node
    participant Calc as Calculator Tool<br/>(calculator_tool.py)
    participant Final as Final Node

    User->>UI: Enter goal & click "Run Agent"
    activate UI
    UI->>Graph: graph.invoke({"goal": goal})
    activate Graph

    Note over Graph: State initialized:<br/>goal = user input

    rect rgb(40, 167, 69, 0.1)
        Note over Graph,Ollama: Phase 1 — Planning
        Graph->>Planner: planner_node(state)
        activate Planner
        Planner->>Agent: create_plan(goal)
        activate Agent
        Agent->>Loader: load_llm()
        activate Loader
        Loader-->>Agent: Ollama LLM instance
        deactivate Loader
        Agent->>Prompt: PromptTemplate(PLANNER_PROMPT)
        Prompt-->>Agent: Formatted prompt with goal
        Agent->>Ollama: chain.invoke({"goal": goal})
        activate Ollama
        Note over Ollama: LLM generates<br/>step-by-step plan
        Ollama-->>Agent: Generated plan text
        deactivate Ollama
        Agent-->>Planner: plan
        deactivate Agent
        Planner-->>Graph: {"plan": plan}
        deactivate Planner
        Note over Graph: State updated:<br/>plan = LLM output
    end

    rect rgb(255, 193, 7, 0.1)
        Note over Graph,Calc: Phase 2 — Tool Execution
        Graph->>Tool: tool_node(state)
        activate Tool
        Tool->>Calc: calculator.invoke("5 * 4")
        activate Calc
        Calc-->>Tool: "20"
        deactivate Calc
        Tool-->>Graph: {"calculation": "20"}
        deactivate Tool
        Note over Graph: State updated:<br/>calculation = "20"
    end

    rect rgb(33, 150, 243, 0.1)
        Note over Graph,Final: Phase 3 — Aggregation
        Graph->>Final: final_node(state)
        activate Final
        Note over Final: Combines goal +<br/>plan + calculation
        Final-->>Graph: {"final_output": formatted_result}
        deactivate Final
        Note over Graph: State updated:<br/>final_output = result
    end

    Graph-->>UI: Complete state with final_output
    deactivate Graph
    UI-->>User: Display formatted result
    deactivate UI
```

---

## 5. State Machine — Automata Diagram

The following **finite state automaton (FSA)** represents the agent's state transitions during execution. Each state corresponds to a node in the LangGraph workflow, and transitions are deterministic.

```mermaid
stateDiagram-v2
    [*] --> Idle: System Ready

    Idle --> GoalReceived: User submits goal
    
    state "Goal Received" as GoalReceived
    state "Planning" as Planning
    state "Executing Tools" as Executing
    state "Aggregating Output" as Aggregating
    state "Complete" as Complete
    state "Error" as Error

    GoalReceived --> Planning: Initialize AgentState\n& enter graph

    state Planning {
        [*] --> LoadLLM
        LoadLLM --> BuildPrompt: LLM loaded
        BuildPrompt --> InvokeLLM: Prompt formatted
        InvokeLLM --> PlanReady: Plan generated
        PlanReady --> [*]
    }

    Planning --> Executing: plan stored in state

    state Executing {
        [*] --> SelectTool
        SelectTool --> RunCalculator: calculator selected
        RunCalculator --> ResultReady: result returned
        ResultReady --> [*]
    }

    Executing --> Aggregating: calculation stored in state

    state Aggregating {
        [*] --> CombineOutputs
        CombineOutputs --> FormatResult: outputs merged
        FormatResult --> [*]
    }

    Aggregating --> Complete: final_output stored in state

    Complete --> Idle: User starts new request
    Complete --> [*]: Session ends

    Planning --> Error: LLM connection failed
    Executing --> Error: Tool execution failed
    Error --> Idle: Error handled / retry
```

### State Transition Table

| Current State      | Event / Trigger                | Next State          | Action                                      |
| ------------------- | ------------------------------ | ------------------- | ------------------------------------------- |
| **Idle**            | User submits goal              | Goal Received       | Capture user input                          |
| **Goal Received**   | Graph invoked                  | Planning            | Initialize `AgentState`, enter graph        |
| **Planning**        | LLM loaded, prompt built       | Planning (internal) | Load Ollama, format prompt, invoke LLM      |
| **Planning**        | Plan generated                 | Executing Tools     | Store plan in state, transition to next node|
| **Planning**        | LLM connection failed          | Error               | Log error, return failure message            |
| **Executing Tools** | Tool selected & executed       | Aggregating Output  | Run calculator, store result in state        |
| **Executing Tools** | Tool execution failed          | Error               | Log error, return failure message            |
| **Aggregating**     | Outputs combined & formatted   | Complete            | Build final output string                    |
| **Complete**        | New goal submitted             | Idle                | Reset state for next invocation              |
| **Error**           | Retry / error handled          | Idle                | Return to ready state                        |

---

## 6. Module Breakdown

### `AgentState` — The Shared State Object

The entire graph communicates through a single typed state dictionary:

```python
class AgentState(TypedDict):
    goal: str           # User's high-level goal (input)
    plan: str           # Generated step-by-step plan (planner output)
    calculation: str    # Tool execution result (tool output)
    final_output: str   # Aggregated final response (final output)
```

### Data mutation through the graph:

```
┌─────────────┬───────────────────┬───────────────────┬───────────────────┐
│   Field     │  After Planner    │  After Tool       │  After Final      │
├─────────────┼───────────────────┼───────────────────┼───────────────────┤
│ goal        │ ✅ "prepare ML.." │ ✅ "prepare ML.." │ ✅ "prepare ML.." │
│ plan        │ ✅ "Step 1:..."   │ ✅ "Step 1:..."   │ ✅ "Step 1:..."   │
│ calculation │ ❌ (empty)        │ ✅ "20"           │ ✅ "20"           │
│ final_output│ ❌ (empty)        │ ❌ (empty)        │ ✅ formatted str  │
└─────────────┴───────────────────┴───────────────────┴───────────────────┘
```

### Graph Construction

```python
workflow = StateGraph(AgentState)

workflow.add_node("planner", planner_node)   # Node 1
workflow.add_node("tool", tool_node)         # Node 2
workflow.add_node("final", final_node)       # Node 3

workflow.set_entry_point("planner")          # Start here

workflow.add_edge("planner", "tool")         # planner → tool
workflow.add_edge("tool", "final")           # tool → final
workflow.add_edge("final", END)              # final → END
```

---

## 7. Class & Type Diagram

```mermaid
classDiagram
    class AgentState {
        <<TypedDict>>
        +str goal
        +str plan
        +str calculation
        +str final_output
    }

    class PlannerAgent {
        +create_plan(goal: str) str
    }

    class LLMLoader {
        +load_llm() Ollama
    }

    class CalculatorTool {
        +calculator(expression: str) str
    }

    class PlannerPrompt {
        +PLANNER_PROMPT: str
    }

    class AgentGraph {
        +build_graph() CompiledGraph
        +planner_node(state: AgentState) dict
        +tool_node(state: AgentState) dict
        +final_node(state: AgentState) dict
    }

    class OllamaServer {
        +model: str = "qwen3:8b"
        +base_url: str = "localhost:11434"
        +temperature: float = 0.5
        +invoke(prompt: str) str
    }

    AgentGraph --> AgentState : manages
    AgentGraph --> PlannerAgent : calls
    AgentGraph --> CalculatorTool : calls
    PlannerAgent --> LLMLoader : loads LLM from
    PlannerAgent --> PlannerPrompt : uses template from
    LLMLoader --> OllamaServer : connects to
```

---

## 8. Deployment Architecture

```mermaid
graph TB
    subgraph "User Machine"
        Browser["🌐 Web Browser<br/>localhost:8501"]
    end

    subgraph "Application Server"
        ST["Streamlit Server<br/>Port 8501"]
        PY["Python Runtime<br/>3.10+"]
        APP["Agentic AI App<br/>LangChain + LangGraph"]
    end

    subgraph "LLM Server"
        OL["Ollama Server<br/>Port 11434"]
        MODEL["Qwen3:8b Model<br/>~5GB VRAM"]
    end

    Browser -->|"HTTP"| ST
    ST --> PY
    PY --> APP
    APP -->|"REST API<br/>localhost:11434/api/generate"| OL
    OL --> MODEL

    style Browser fill:#4A90D9,color:#fff
    style ST fill:#FF4B4B,color:#fff
    style PY fill:#3776AB,color:#fff
    style APP fill:#FF6F00,color:#fff
    style OL fill:#000,color:#fff
    style MODEL fill:#1A1A2E,color:#fff
```

| Component         | Port   | Protocol | Notes                           |
| ----------------- | ------ | -------- | ------------------------------- |
| Streamlit UI      | `8501` | HTTP     | User-facing web interface       |
| Ollama API        | `11434`| HTTP     | LLM inference endpoint          |

---

## 9. Design Decisions

| Decision                         | Rationale                                                                                      |
| -------------------------------- | ---------------------------------------------------------------------------------------------- |
| **LangGraph over simple chains** | Enables stateful, graph-based orchestration with clear node boundaries and future branching     |
| **Ollama for local LLM**         | Zero-cost, fully private inference with no API keys or cloud dependency                        |
| **Qwen3:8b model**               | Strong instruction-following at a reasonable hardware footprint (~5 GB VRAM)                   |
| **Streamlit for UI**             | Rapid prototyping with minimal frontend code; ideal for AI/ML demos                            |
| **TypedDict for state**          | Type-safe state management with clear schema; compatible with LangGraph's state system         |
| **Modular folder structure**     | Agents, tools, prompts, and utilities are decoupled for independent development and testing     |
| **Deterministic edges**          | Linear `planner → tool → final` flow keeps the system predictable and debuggable               |

---

<div align="center">

*This document is part of the [Agentic AI Demo](README.md) project.*

</div>
