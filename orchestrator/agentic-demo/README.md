<div align="center">

# 🤖 Agentic AI Planner

### Goal-Driven Autonomous Planning Agent Powered by Local LLMs

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-Framework-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://www.langchain.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6F00?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

---

**Agentic AI Planner** is a modular, graph-based autonomous agent system that breaks down high-level user goals into actionable plans, executes tool-augmented tasks, and delivers structured results — all powered by a locally-hosted LLM via Ollama.

*No API keys. No cloud dependency. Fully local & private.*

</div>

---

## 📑 Table of Contents

- [Features](#-features)
- [Demo / Screenshots](#-demo--screenshots)
- [Architecture](#-architecture) ← *Full system design document*
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Installation & Setup](#-installation--setup)
- [Usage](#-usage)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Contributing](#-contributing)
- [Roadmap / Future Improvements](#-roadmap--future-improvements)
- [License](#-license)
- [Contact / Author](#-contact--author)

---

## ✨ Features

- **🧠 Autonomous Planning** — Accepts a high-level goal and generates a step-by-step execution plan using an AI planning agent.
- **🔗 Graph-Based Orchestration** — Uses LangGraph to define a stateful, multi-node workflow (`Planner → Tool → Final Output`).
- **🛠️ Tool-Augmented Execution** — Integrates custom tools (e.g., calculator) that the agent can invoke during the workflow.
- **💻 100% Local Inference** — Runs entirely on your machine using Ollama with the Qwen3:8b model — no API keys or cloud services required.
- **🖥️ Interactive Web UI** — Provides a clean Streamlit-based interface for goal input and result visualization.
- **📦 Modular Architecture** — Clean separation of agents, tools, prompts, graph logic, and utilities for easy extensibility.

---

## 📸 Demo / Screenshots

> **🚧 Coming Soon** — Screenshots and a live demo link will be added here.
>
> To try it locally, follow the [Installation & Setup](#-installation--setup) section below.

<!-- Add screenshots here:
![Demo Screenshot](docs/images/demo.png)
-->

---

## 🏗️ Architecture

> 📄 **[View Full System Design & Architecture Document →](ARCHITECTURE.md)**
> *Includes sequence diagrams, state machine automata, class diagrams, and deployment architecture.*

The agent follows a **three-node state graph** workflow:

```
┌─────────────────────────────────────────────────────┐
│                    User Goal                        │
│             "Help me prepare for ML exam"           │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │   🧠 Planner   │  ← Breaks goal into sub-tasks
              │    Node        │    using Qwen3 via Ollama
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │   🛠️  Tool     │  ← Executes tool-augmented
              │    Node        │    actions (e.g., calculator)
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │   📋 Final     │  ← Aggregates plan + tool
              │    Node        │    results into final output
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │    ✅ END      │
              └────────────────┘
```

---

## 🛠️ Tech Stack

| Layer             | Technology                                                          |
| ----------------- | ------------------------------------------------------------------- |
| **LLM Runtime**   | [Ollama](https://ollama.com/) + [Qwen3:8b](https://ollama.com/library/qwen3) |
| **Framework**     | [LangChain](https://www.langchain.com/)                             |
| **Orchestration** | [LangGraph](https://langchain-ai.github.io/langgraph/)             |
| **Frontend / UI** | [Streamlit](https://streamlit.io/)                                  |
| **Language**      | Python 3.10+                                                        |
| **Env Management**| `venv` + `pip`                                                      |

---

## 📁 Project Structure

```
agentic-ai-demo/
│
├── agents/
│   └── planner_agent.py        # Planning agent — generates step-by-step plans
│
├── graph/
│   └── agent_graph.py          # LangGraph state graph definition & workflow
│
├── prompts/
│   └── planner_prompt.py       # Prompt template for the planner agent
│
├── tools/
│   └── calculator_tool.py      # Calculator tool (LangChain @tool)
│
├── utils/
│   └── llm_loader.py           # Loads Ollama LLM (Qwen3:8b)
│
├── app.py                      # Streamlit web UI entry point
├── main.py                     # CLI entry point
├── test_llm.py                 # Test script — LLM connectivity
├── test_planner.py             # Test script — planner agent
├── test_tool.py                # Test script — calculator tool
├── requirements.txt            # Python dependencies
├── ARCHITECTURE.md             # System design & architecture document
└── README.md
```

---

## 🚀 Installation & Setup

### Prerequisites

| Requirement    | Version  | Notes                            |
| -------------- | -------- | -------------------------------- |
| **Python**     | ≥ 3.10   | Required                         |
| **Ollama**     | Latest   | [Install Guide](https://ollama.com/download) |
| **Git**        | Latest   | To clone the repository          |

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/agentic-ai-demo.git
cd agentic-ai-demo
```

### 2. Create & Activate a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate          # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install & Start Ollama

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh

# Pull the Qwen3:8b model
ollama pull qwen3:8b

# Start the Ollama server (if not running)
ollama serve
```

### 5. Environment Variables *(Optional)*

Create a `.env` file in the project root if you need to customize settings:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
```

> **Note:** The default configuration connects to `http://localhost:11434` with the `qwen3:8b` model. No `.env` file is needed for default usage.

---

## 💡 Usage

### Option 1: Streamlit Web UI *(Recommended)*

```bash
streamlit run app.py
```

This launches an interactive web interface where you can:
1. Enter a high-level goal (e.g., *"Help me prepare for ML exam in 5 days"*)
2. Click **Run Agent**
3. View the generated plan and tool execution results

### Option 2: Command-Line Interface

```bash
python main.py
```

**Example Output:**

```
AGENT OUTPUT:

Goal:
Help me prepare for ML exam in 5 days

Plan:
Step 1: Review core ML concepts (supervised, unsupervised, reinforcement learning)
Step 2: Practice key algorithms — linear regression, decision trees, SVM, KNN
Step 3: Work through hands-on projects and Kaggle datasets
Step 4: Take timed practice tests
Step 5: Revise weak areas and review notes

Calculation Result:
20
```

---

## 🧪 Testing

Run the individual test scripts to verify each component:

```bash
# Test LLM connectivity
python test_llm.py

# Test the planner agent
python test_planner.py

# Test the calculator tool
python test_tool.py
```

| Script              | Purpose                                      |
| ------------------- | -------------------------------------------- |
| `test_llm.py`       | Verifies Ollama/Qwen3 connectivity           |
| `test_planner.py`   | Tests goal → plan generation                 |
| `test_tool.py`      | Tests calculator tool invocation             |

> **Tip:** Ensure the Ollama server is running (`ollama serve`) before executing tests.

---

## 🌐 Deployment

### Local Deployment

The application is designed for **local-first deployment**. Simply follow the [Installation & Setup](#-installation--setup) steps.

### Docker *(Future)*

A Dockerfile and `docker-compose.yml` will be provided in a future release for containerized deployment.

### Cloud Deployment

To deploy on a cloud VM (e.g., AWS EC2, GCP Compute Engine):

1. Provision a VM with **≥ 8 GB RAM** (for the Qwen3:8b model)
2. Install Python 3.10+, Ollama, and project dependencies
3. Run `ollama pull qwen3:8b && ollama serve &`
4. Run `streamlit run app.py --server.port 8501 --server.address 0.0.0.0`
5. Open `http://<VM_PUBLIC_IP>:8501` in your browser

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Commit** your changes with clear, descriptive messages:
   ```bash
   git commit -m "feat: add web search tool to agent workflow"
   ```
4. **Push** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
5. **Open a Pull Request** with a clear description of your changes

### Contribution Guidelines

- Follow existing code structure and naming conventions
- Add test scripts for new tools or agents
- Update the README if you add new features
- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages

---

## 🗺️ Roadmap / Future Improvements

- [ ] 🔍 **Web Search Tool** — Add internet search capabilities to the agent
- [ ] 🧠 **Memory & Context** — Implement conversation memory for multi-turn interactions
- [ ] 🔄 **Dynamic Tool Selection** — Let the agent decide which tools to use based on the goal
- [ ] 📄 **Document Summarizer** — Add a tool for summarizing PDFs and web pages
- [ ] 🐳 **Docker Support** — Containerize the full stack (app + Ollama)
- [ ] 🔀 **Conditional Graph Routing** — Add branching logic in the workflow graph
- [ ] 📊 **Execution Dashboard** — Visualize agent execution traces and graph state
- [ ] 🧪 **Unit Test Suite** — Comprehensive `pytest`-based test coverage
- [ ] 🤖 **Multi-Agent Support** — Orchestrate multiple specialized agents

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2025 [Your Name]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

---

## 👤 Contact / Author

| Field       | Details                                         |
| ----------- | ----------------------------------------------- |
| **Author**  | *Your Name*                                     |
| **Email**   | *your.email@example.com*                        |
| **GitHub**  | [github.com/your-username](https://github.com/AMAANALI70) |
| **LinkedIn**| [linkedin.com/in/your-profile](https://linkedin.com/in/your-profile) |

---

<div align="center">

**⭐ If you found this project useful, give it a star on GitHub! ⭐**

*Built with ❤️ using LangChain, LangGraph, Ollama & Streamlit*

</div>
