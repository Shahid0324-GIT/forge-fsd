"""Decode one complete source file without JSON-string escaping."""
import re

from pydantic import RootModel


class SourceText(RootModel[str]):pass


def decode_source(text):
    if not isinstance(text,str):raise ValueError('Expected source text, not multipart content')
    source=text.strip()
    if source.startswith('```'):
        match=re.fullmatch(r'```[a-zA-Z0-9_+\-]*[ \t]*\r?\n([\s\S]*?)\r?\n```',source)
        if not match or re.search(r'(?m)^```',match[1]):raise ValueError('Expected one complete source block, not incomplete or multiple files')
        source=match[1].strip()
    if not source:raise ValueError('Source response is empty')
    if len(source)+1>24000:raise ValueError('Source response exceeds the complete-file budget; it was not truncated')
    return source+'\n'
