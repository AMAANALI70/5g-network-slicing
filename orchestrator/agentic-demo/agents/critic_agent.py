from langchain_core.prompts import PromptTemplate
from utils.llm_loader import load_llm

CRITIC_PROMPT = """
You are a Critic Agent.

Your job is to evaluate whether the following plan is feasible
for achieving the given goal within the specified time.

Goal:
{goal}

Plan:
{plan}

Provide:
- Feasibility Assessment
- Suggestions for Improvement
"""

def review_plan(goal, plan):

    llm = load_llm()

    prompt = PromptTemplate(
        input_variables=["goal", "plan"],
        template=CRITIC_PROMPT
    )

    chain = prompt | llm

    review = chain.invoke({
        "goal": goal,
        "plan": plan
    })

    return review

