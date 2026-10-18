import pytest
from check_local_recovery import validate_local


def config():
    return {
        "ENVIRONMENT": "testing",
        "CHAIN_ID": "31337",
        "DATABASE_URL": "postgresql://test:local@postgres:5432/veritras_test",
        "SEPOLIA_RPC_URL": "http://blockchain:8545",
    }


def test_local_drill_accepts_only_its_named_compose_stack():
    db, api, rpc = validate_local(config(), {"chainId": 31337})
    assert db.database == "veritras_test" and api == "http://127.0.0.1:8000"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ENVIRONMENT", "production"),
        ("CHAIN_ID", "11155111"),
        ("DATABASE_URL", "postgresql://test:local@production.neon.tech/veritras_test"),
        ("DATABASE_URL", "postgresql://test:local@localhost/neondb"),
        ("DATABASE_URL", "sqlite:///testing.db"),
        ("SEPOLIA_RPC_URL", "https://sepolia.example.com"),
        ("SEPOLIA_RPC_URL", "http://secret:password@blockchain:8545"),
        ("LOCAL_RECOVERY_API", "https://veritras-api-testing.onrender.com"),
        ("LOCAL_RECOVERY_API", "http://backend:8000/?secret=x"),
    ],
)
def test_fault_injection_refuses_hosted_or_mismatched_configuration(field, value):
    env = config()
    env[field] = value
    with pytest.raises(RuntimeError):
        validate_local(env, {"chainId": 31337})


def test_fault_injection_refuses_a_hosted_contract_manifest():
    with pytest.raises(RuntimeError):
        validate_local(config(), {"chainId": 11155111})
