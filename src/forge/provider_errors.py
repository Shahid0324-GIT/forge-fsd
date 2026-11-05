"""Provider capacity/access failures are not evidence of an application defect."""
import re

from httpx import TransportError
from ollama import ResponseError


class ProviderResourceError(RuntimeError):
    pass


def classify_provider_error(error):
    """Transport/service failures cannot be repaired by changing app source."""
    if isinstance(error,ProviderResourceError):return error
    if isinstance(error,(ConnectionError,TimeoutError,OSError,TransportError,ResponseError)):
        return ProviderResourceError('Model provider is unavailable or rejected the request; check service, model and capacity before resuming. No app defect inferred.')
    return error


def legacy_resource_failure(error):
    """Recognize saved pre-typed provider errors without reclassifying app failures."""
    return bool(re.match(r'^(?:RuntimeError:\s*)?Groq API returned HTTP (?:401|403|413|429)(?:[;\s]|$)',error)
        or re.match(r'^ValueError: Source response did not complete normally(?:[.;\s]|$)',error))
