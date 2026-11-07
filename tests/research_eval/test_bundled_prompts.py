"""Public prompt cores are data with exact upstream identities, never authority."""

import hashlib

from research_eval.bundled_prompts import prompt_cores


def test_exact_three_public_prompt_cores() -> None:
    expected = {
        "W1_MINIMAL2_FINANCIAL_CORE_V1": (
            "baa2c6d7b27841d492a5d0d346e570f36b567cd57b1ec009043837f0265e109b"
        ),
        "w3-causal-v1": (
            "275890333fc9242807cba28945c663b76f6cc222957dcf4fecf22f93b2802ac4"
        ),
        "w3-b-evidence-v1": (
            "b1c77a397891d3f98a695ee805597e482921c5c127024a34ce1a437cb83b10e7"
        ),
    }
    cores = prompt_cores()
    assert set(cores) == set(expected)
    assert {
        k: hashlib.sha256(v.encode()).hexdigest() for k, v in cores.items()
    } == expected
