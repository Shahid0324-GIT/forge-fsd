from types import SimpleNamespace

import pytest

from forge.agents import OllamaAgents
from forge.schemas import RequirementsDocument


class FakeModel:
    def __init__(self, response):
        self.response = response

    def with_structured_output(self, schema, **kwargs):
        assert kwargs == {"method": "json_schema", "include_raw": True}
        return self

    def invoke(self, messages):
        return self.response


@pytest.mark.parametrize("reason", ["length", None])
def test_incomplete_model_response_is_rejected(reason):
    agents = OllamaAgents.__new__(OllamaAgents)
    agents.model = FakeModel({"raw": SimpleNamespace(response_metadata={"done_reason": reason}),
                              "parsed": {}, "parsing_error": None})
    with pytest.raises(ValueError, match="did not complete normally"):
        agents.generate(RequirementsDocument, "instruction", {})


def test_provider_parse_failure_is_rejected():
    agents = OllamaAgents.__new__(OllamaAgents)
    agents.model = FakeModel({"parsing_error": "invalid JSON"})
    with pytest.raises(ValueError, match="invalid JSON"):
        agents.generate(RequirementsDocument, "instruction", {})
