"""
Shared pytest fixtures for the Shadow QA test suite.

inject_llm_gateway_test_name — autouse fixture that stamps the current test
name into the environment before every test so that outgoing LLM gateway
requests carry an X-Test-Name header identifying the caller. The variable is
cleaned up after yield so it never leaks between tests or into production code
that runs outside pytest.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def inject_llm_gateway_test_name(request):
    """
    Set LLM_GATEWAY_TEST_NAME to the running test's node name for the duration
    of each test, then restore the prior value (or remove it entirely).

    All outgoing HTTP clients read this env var and forward it as X-Test-Name,
    which lets the local LLM gateway logs be correlated back to individual tests.
    """
    env_key = "LLM_GATEWAY_TEST_NAME"
    prior = os.environ.get(env_key)          # None if not previously set
    os.environ[env_key] = request.node.name

    yield

    # Restore exactly: remove the key if it wasn't present before, otherwise
    # put the old value back. This is safe even when tests run in parallel.
    if prior is None:
        os.environ.pop(env_key, None)
    else:
        os.environ[env_key] = prior
