import streamlit as st
from graph.agent_graph import build_graph

st.set_page_config(page_title="Agentic AI Demo", layout="centered")

st.title("🤖 Agentic AI System (Local LLM Powered)")
st.write("Goal Driven Autonomous Planning Agent using Qwen3 via Ollama")

goal = st.text_input("Enter Your Goal:")

if st.button("Run Agent"):

    if goal:

        st.write("### 🧠 Running Agent Workflow...")

        graph = build_graph()

        result = graph.invoke({
            "goal": goal
        })

        st.write("### 📌 Final Output")
        st.code(result["final_output"])

    else:
        st.warning("Please enter a goal!")

