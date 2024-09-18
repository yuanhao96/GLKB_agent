from typing import List, TypedDict


class GraphState(TypedDict):
    """
    Represents the state of our graph.

    Attributes:
        question: question
        steps: plan to answer the question
        context: context of each step
        prompt_context: list of context from previous steps to form qa prompt
        prompt: prompt template object
        prompt_with_context: prompt template with context from vector search
        answer: answer to the question
    """

    question: str
    steps: object
    context: dict
    prompt_context: list
    prompt: object
    prompt_with_context: object
    answer: str