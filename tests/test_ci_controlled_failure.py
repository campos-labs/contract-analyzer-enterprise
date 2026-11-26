import pytest


def test_ci_rejects_controlled_failure():
    pytest.fail('Falha controlada para validar o CI da issue #4')
