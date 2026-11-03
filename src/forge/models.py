"""Supported inference choices; jobs retain their provider across worker restarts."""
from typing import Literal

LocalModel=Literal['qwen2.5-coder:3b','qwen2.5-coder:7b']
AgentModel=Literal['qwen2.5-coder:3b','qwen2.5-coder:7b','groq:openai/gpt-oss-120b','groq:openai/gpt-oss-20b']
SUPPORTED_MODELS={'qwen2.5-coder:3b','qwen2.5-coder:7b','groq:openai/gpt-oss-120b','groq:openai/gpt-oss-20b'}
DEFAULT_MODEL='qwen2.5-coder:3b'


def job_model(record):
    for event in reversed(record['events']):
        if event['status'] in {'RECEIVED','MODEL_SELECTED'} and event['payload'].get('model') in SUPPORTED_MODELS:
            return event['payload']['model']
    return 'qwen2.5-coder:3b'
