from langchain_community.llms import Ollama

def load_llm():
    llm = Ollama(
        model="qwen3:8b",
        base_url="http://localhost:11434",
        temperature=0.5
    )
    return llm

