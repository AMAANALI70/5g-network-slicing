from langchain_core.prompts import PromptTemplate
from utils.llm_loader import load_llm
from prompts.planner_prompt import PLANNER_PROMPT

def create_plan(goal):

    llm = load_llm()

    prompt = PromptTemplate(
        input_variables=["goal"],
        template=PLANNER_PROMPT
    )

    chain = prompt | llm

    plan = chain.invoke({"goal": goal})

    return plan

