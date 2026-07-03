from agents.planner_agent import create_plan

goal = "Help me prepare for Machine Learning exam in 5 days"

plan = create_plan(goal)

print("\nGenerated Plan:\n")
print(plan)

