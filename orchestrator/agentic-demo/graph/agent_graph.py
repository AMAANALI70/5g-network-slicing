from typing import TypedDict
from langgraph.graph import StateGraph, END

from agents.planner_agent import create_plan
from agents.critic_agent import review_plan
from tools.calculator_tool import calculator

class AgentState(TypedDict):
    goal: str
    plan: str
    calculation: str
    review: str
    final_output: str

# Planner Agent Node
def planner_node(state: AgentState):
    goal = state["goal"]
    plan = create_plan(goal)
    return {"plan": plan}

# Executor Tool Node
def tool_node(state: AgentState):
    calc = calculator.invoke("10 * 2")
    return {"calculation": calc}

# Critic Agent Node
def critic_node(state: AgentState):
    review = review_plan(state["goal"], state["plan"])
    return {"review": review}

# Final Output Node
def final_node(state: AgentState):
    output = f"""
Goal:
{state['goal']}

Plan:
{state['plan']}

Estimated Workload:
{state['calculation']}

Critic Review:
{state['review']}
"""
    return {"final_output": output}

# Build Graph
def build_graph():

    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", tool_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("final", final_node)

    workflow.set_entry_point("planner")

    workflow.add_edge("planner", "executor")
    workflow.add_edge("executor", "critic")
    workflow.add_edge("critic", "final")
    workflow.add_edge("final", END)

    return workflow.compile()

