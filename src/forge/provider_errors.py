"""Provider capacity/access failures are not evidence of an application defect."""
import re


class ProviderResourceError(RuntimeError):
    pass


def legacy_resource_failure(error):
    """Recognize saved pre-typed provider errors without reclassifying app failures."""
    return bool(re.match(r'^(?:RuntimeError:\s*)?Groq API returned HTTP (?:401|403|413|429)(?:[;\s]|$)',error))
