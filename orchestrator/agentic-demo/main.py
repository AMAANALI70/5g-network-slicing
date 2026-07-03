from graph.agent_graph import build_graph

graph = build_graph()

result = graph.invoke({
    "goal": "Help me prepare for ML exam in 5 days"
})

print("\nAGENT OUTPUT:\n")
print(result["final_output"])

