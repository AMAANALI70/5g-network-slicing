from langchain_core.tools import tool

@tool
def calculator(expression: str) -> str:
    """
    Use this tool to perform mathematical calculations.
    Input should be a valid mathematical expression.
    Example: "5*3", "100/4"
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

