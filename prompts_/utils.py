import json
from test_questions import test_questions
from copy import deepcopy
import random
from typing import Tuple
import json

def split_example_test_set(examples: list, example_ratio: float) -> Tuple[list, list]:
    examples = deepcopy(examples)
    random.shuffle(examples)
    example_num = round(len(examples) * example_ratio)
    return (examples[:example_num], examples[example_num:])

def generate_my_prompt(examples: list):
    my_prompt = open('./my_prompt.txt', 'r').read()
    e = ''
    for example in examples:
        e += f'Q: {example["q"]}\n'
        e += f'A: {example["a"]}\n\n'
    my_prompt = my_prompt.replace('$examples$', e)
    return my_prompt

# examples, tests = split_example_test_set(test_questions, 0.6)
# print(generate_my_prompt(examples))
# print(json.dumps(tests, indent=2, ensure_ascii=False))