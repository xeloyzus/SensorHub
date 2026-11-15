"""First-run configuration must be complete and must preserve existing secrets."""

import re

import pytest

from scripts.setup_env import SECRET_KEYS, create_env, main, site_address


def test_generated_environment_has_distinct_secrets_and_matching_database_url(tmp_path):
    target = tmp_path / '.env'
    create_env('http://192.0.2.10', target)
    values = dict(line.split('=', 1) for line in target.read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    assert values['DOMAIN'] == 'http://192.0.2.10'
    assert len({values[key] for key in SECRET_KEYS}) == 4
    assert all(re.fullmatch('[0-9a-f]{64}', values[key]) for key in SECRET_KEYS)
    assert values['DATABASE_URL'] == f"postgresql://naniteslab:{values['POSTGRES_PASSWORD']}@timescaledb:5432/naniteslab"
    assert 'DEMO_MODE' not in values
    assert b'\r' not in target.read_bytes()


def test_existing_environment_is_never_overwritten(tmp_path, capsys):
    target = tmp_path / '.env'
    original = 'POSTGRES_PASSWORD=existing-database-secret\n'
    target.write_text(original)
    with pytest.raises(FileExistsError):
        create_env('dashboard.uis.no', target)
    assert main(['--domain', 'dashboard.uis.no', '--output', str(target)]) == 1
    assert target.read_text() == original
    assert 'existing-database-secret' not in capsys.readouterr().err


def test_local_setup_does_not_require_a_fixed_ip_or_hostname(tmp_path, capsys):
    target = tmp_path / '.env'
    assert main(['--local', '--output', str(target)]) == 0
    content = target.read_text()
    assert 'DOMAIN=http://\n' in content
    assert 'HTTP_PORT=8080\n' in content
    assert 'http://localhost:8080' in capsys.readouterr().out


@pytest.mark.parametrize('port', [0, 65536])
def test_invalid_published_port_does_not_create_environment(port, tmp_path):
    target = tmp_path / '.env'
    with pytest.raises(ValueError):
        create_env('http://', target, http_port=port)
    assert not target.exists()


@pytest.mark.parametrize('address, expected', [
    ('dashboard.uis.no', 'dashboard.uis.no'),
    ('http://192.0.2.10/', 'http://192.0.2.10'),
    ('192.0.2.10', 'http://192.0.2.10'),
    ('localhost', 'http://localhost'),
    ('http://[::1]', 'http://[::1]'),
])
def test_hostname_and_local_http_addresses(address, expected):
    assert site_address(address) == expected


@pytest.mark.parametrize('address', ['', 'dashboard.example.com', 'http://host/path', 'http://user:pass@host', 'host\nPOSTGRES_PASSWORD=bad', 'http://host:8000', 'ftp://host', '${DOMAIN}', 'bad..host'])
def test_invalid_address_cannot_inject_environment_configuration(address, tmp_path):
    target = tmp_path / '.env'
    with pytest.raises(ValueError):
        create_env(address, target)
    assert not target.exists()
