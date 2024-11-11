from test_questions import test_questions
import openai
import sys
sys.path.append('..')
from config import OPENAI_API_KEY
from neo4j_ import run_cypher
from utils import split_example_test_set, generate_my_prompt

client = openai.Client(api_key=OPENAI_API_KEY)

origin_prompt_with_all_examples = open('./origin_prompt_all_examples.txt').read()
my_prompt = ''  # set later
my_prompt_2 = open('./my_prompt_2.txt').read()


def get_answers_for_origin_prompt(prompt: str, questions: list):
    answers = []
    try:
        for q in questions:
            question = q['q']
            this_prompt = prompt.replace('$user-query$', question)
            messages = [{'role': 'user', 'content': this_prompt}]
            resp = client.chat.completions.create(messages=messages, model='gpt-4o', temperature=0.3, top_p=1.0)
            answer = resp.choices[0].message.content
            answers.append(answer)
    except:
        print(answers)
        raise
    return answers


def get_answers_for_my_prompt(prompt: str, questions: list):
    answers = []
    try:
        for q in questions:
            question = q['q']
            messages = [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': question}
            ]
            resp = client.chat.completions.create(messages=messages, model='gpt-4o', temperature=0.3, top_p=1.0)
            answer = resp.choices[0].message.content
            messages.append({'role': 'assistant', 'content': answer})
            messages.append({'role': 'user', 'content': my_prompt_2})
            resp2 = client.chat.completions.create(messages=messages, model='gpt-4o', temperature=0.3, top_p=1.0)
            answer2 = resp2.choices[0].message.content
            answers.append(answer2)
    except:
        print(answers)
        raise
    return answers


def compare_answers(questions: list, origin_prompt_answers: list[str], my_prompt_answers: list[str]):
    assert (len(questions) == len(origin_prompt_answers))
    assert (len(questions) == len(my_prompt_answers))
    length = len(questions)
    for i in range(0, length):
        question = questions[i]['q']
        expected = questions[i]['a']
        origin_prompt_answer = origin_prompt_answers[i]
        my_prompt_answer = my_prompt_answers[i]
        print(f'{i + 1}. Question: {question}')
        print(f'Expected: {expected}')
        print(f'Orig_ans: {origin_prompt_answer}')
        print(f'My___ans: {my_prompt_answer}')
        expected_result = run_cypher(expected)
        try:
            origin_result = run_cypher(origin_prompt_answer)
        except:
            origin_result = 'ERROR'
        try:
            my_result = run_cypher(my_prompt_answer)
        except:
            my_result = 'ERROR'
        print(f'Expected: {expected_result}')
        print(f'Orig_res: {origin_result}')
        print(f'My___res: {my_result}')
        print("")
    


if __name__ == '__main__':
    examples_set, tests_set = split_example_test_set(test_questions, 0.6)
    my_prompt = generate_my_prompt(examples_set)
    print('Using test set:\n' + str(tests_set) + '\n')

    # print(my_prompt)
    # print(my_prompt_2)
    # raise

    answers = get_answers_for_origin_prompt(origin_prompt_with_all_examples, tests_set)
    print("Answers with original prompt:\n" + str(answers) + '\n')

    my_prompt_answers = get_answers_for_my_prompt(my_prompt, tests_set)
    print("Answers with my prompt:\n" + str(my_prompt_answers) + '\n')
    
    compare_answers(tests_set, answers, my_prompt_answers)
