#!/usr/bin/env python3
import json
import uuid
import sys
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

from .utils import get_env_variable
from .schema_loader import get_schema, get_schema_hints, get_example_queries

import os
from pathlib import Path

load_dotenv()

# Configure OpenAI client
openai_client = OpenAI(
    base_url=get_env_variable("OPENAI_API_BASE_URL"),
    api_key=get_env_variable("OPENAI_API_KEY")
)

SYSTEM_RULES = (
    "You are a Cypher-generating assistant. Follow these rules:\n"
    "1. Use *only* the node labels, relationship types and property names that appear in the JSON schema.\n"
    "2. Respond with converted Cypher query directly - no any other text or explanation.\n"
    "3. Return nodes and relationships only (omit scalar property values in RETURN).\n"
    "4. When the user mentions a label/relationship/property absent from the schema, first map it to the closest existing element (exact synonym, substring, or highest-similarity fuzzy match).\n"
    "5. if needed (the most important genes, etc.), add order by clause to the query"
    "6. always add limit clause to the query except for aggregate queries (count, sum, avg, min, max, etc.)"
    "7. When the user mentions a label/relationship/property out of scope, return an empty string."
    "8. Always return properties of the nodes and relationships in the query, instead of the nodes / relationships / patterns themselves. i.e., return article.title, article.pubdate, etc. instead of article."
)

SYSTEM_RULES_FORMATTED = (
    "You are a Cypher-generating assistant. Follow these rules:\n"
    "1. Use *only* the node labels, relationship types and property names that appear in the JSON schema.\n"
    "2. Respond with a JSON object with the following format.\n"
    "3. Rephrase the question into formatted question using entities and relationships in the schema.\n"
    "4. Return nodes and relationships only (omit scalar property values in RETURN).\n"
    "5. When the user mentions a label/relationship/property absent from the schema, first map it to the closest existing element (exact synonym, substring, or highest-similarity fuzzy match).\n"
    "6. if needed (the most important genes, etc.), add order by clause to the query\n"
    "7. always add limit clause to the query except for aggregate queries (count, sum, avg, min, max, etc.)"
    "8. When the user mentions a label/relationship/property out of scope, return an empty string."
    "9. Always return properties of the nodes and relationships in the query, instead of the nodes / relationships / patterns themselves. i.e., return article.title, article.pubdate, etc. instead of article."

    """rephrase example:
    input: Which SNPs are associated with BRCA1 expression through eQTL relationships?
    rephrase: Which @@{sequence_variant}{SNPs} are associated with @@{gene}{BRCA1} expression through eQTL relationships?"""

    """response JSON format: {{
    "in_scope": boolean that determines if the question is in the scope of the schema,
    "rephrase": Rephrased question using entities and relationships in the schema,
    "cypher_query": Valid Cypher query or empty string if out of scope
    }}"""
)

class Text2CypherAgent:
    """Single-LLM agent that remembers conversation context + schema."""

    def __init__(self, provider: str = "openai", formatted_output: bool = False):
        self.provider = provider
        self.schema_json = get_schema()
        self.schema_str = json.dumps(self.schema_json, indent=2)
        self.hints = get_schema_hints()
        self.model = get_env_variable("OPENAI_API_MODEL")
        self.formatted_output = formatted_output
        self.example_queries = get_example_queries()
        
        # Build system prompt with schema and optional hints
        whole_schema = self.schema_str.replace('{', '{{').replace('}', '}}')
        if self.formatted_output:
            system_prompt = SYSTEM_RULES_FORMATTED + "\n### Schema\n" + whole_schema
        else:
            system_prompt = SYSTEM_RULES + "\n### Schema\n" + whole_schema
        
        if self.hints:
            hints_str = json.dumps(self.hints, indent=2).replace('{', '{{').replace('}', '}}')
            system_prompt += "\n\n### Schema Hints\n" + hints_str

        if self.example_queries:
            example_queries_str = "\n".join([f"Example {i+1}: Question: {query['question']}\nQuery: {query['query']}" for i, query in enumerate(self.example_queries)])
            system_prompt += "\n\n### Example Queries\n" + example_queries_str

        self.system_prompt = system_prompt
        self.chat_history: List[Dict[str, str]] = []

    def respond(self, user_text: str) -> str:
        # Build messages list with system prompt, history, and current user input
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Add chat history
        for message in self.chat_history:
            messages.append(message)
        
        # Add current user input
        messages.append({"role": "user", "content": user_text})
        
        print(f"[Text2Cypher] Processing query: {user_text}", file=sys.stderr)
        print(f"[Text2Cypher] Using model: {self.model}, formatted_output: {self.formatted_output}", file=sys.stderr)
        print(f"[Text2Cypher] Chat history length: {len(self.chat_history)}", file=sys.stderr)
        
        try:
            if self.formatted_output:
                print("[Text2Cypher] Making OpenAI API call with JSON response format", file=sys.stderr)
                response = openai_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                    max_tokens=1000,
                    response_format={"type": "json_object"}
                )
            else:
                print("[Text2Cypher] Making OpenAI API call with text response format", file=sys.stderr)
                response = openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=1000
                )

            # Extract assistant response
            assistant_response = response.choices[0].message.content.strip()
            
            print(f"[Text2Cypher] Received response: {assistant_response}", file=sys.stderr)
            print(f"[Text2Cypher] Response length: {len(assistant_response)}", file=sys.stderr)
            
            # Update chat history
            self.chat_history.append({"role": "user", "content": user_text})
            self.chat_history.append({"role": "assistant", "content": assistant_response})
            
            # Keep only last 10 message pairs to prevent context from getting too long
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
            
            final_response = assistant_response.strip().strip("` ")
            print(f"[Text2Cypher] Final response: {final_response}", file=sys.stderr)
            
            return final_response
            
        except Exception as e:
            error_msg = f"Error calling OpenAI API: {e}"
            print(error_msg, file=sys.stderr)
            print(f"[Text2Cypher] Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"[Text2Cypher] Exception details: {str(e)}", file=sys.stderr)
            import traceback
            print(f"[Text2Cypher] Traceback: {traceback.format_exc()}", file=sys.stderr)
            return f"Error: {str(e)}"

    def get_history(self) -> List[Dict[str, str]]:
        """Return chat history as list of {role, content} dicts."""
        return self.chat_history.copy()

    def clear_history(self) -> None:
        """Clear the chat history."""
        self.chat_history = []

if __name__ == "__main__":
    try:
        agent = Text2CypherAgent()
    except EnvironmentError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        while True:
            txt = input("You> ").strip()
            if not txt:
                continue
            print(agent.respond(txt) + "\n")
    except (KeyboardInterrupt, EOFError):
        print()