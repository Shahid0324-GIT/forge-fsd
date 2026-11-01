"""Supported local models; jobs retain their choice across worker restarts."""
from typing import Literal

LocalModel=Literal['qwen2.5-coder:3b','qwen2.5-coder:7b']
DEFAULT_MODEL='qwen2.5-coder:3b'


def job_model(record):
    for event in reversed(record['events']):
        if event['status'] in {'RECEIVED','MODEL_SELECTED'} and event['payload'].get('model') in {'qwen2.5-coder:3b','qwen2.5-coder:7b'}:
            return event['payload']['model']
    return 'qwen2.5-coder:3b'
