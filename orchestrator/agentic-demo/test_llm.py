from utils.llm_loader import load_llm

llm = load_llm()

response = llm.invoke("Explain what an AI agent is in one line.")

print(response)

