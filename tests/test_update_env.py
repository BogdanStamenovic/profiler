import os

import pytest
from conftest import load_script

update_env = load_script("update_env")
PATTERN = r"^(?:APP_[A-Z0-9_]+|API_KEY)$"


def test_atomic_update_preserves_other_values_and_mode(tmp_path):
    path = tmp_path / "app.env"
    path.write_text("APP_NAME=old\nAPI_KEY=secret\n")
    path.chmod(0o640)

    update_env.set_value(path, "APP_NAME", "new", PATTERN)

    assert path.read_text() == "APP_NAME=new\nAPI_KEY=secret\n"
    assert os.stat(path).st_mode & 0o777 == 0o640


def test_rejects_unknown_keys_and_whitespace(tmp_path):
    path = tmp_path / "app.env"
    path.write_text("")
    with pytest.raises(ValueError):
        update_env.set_value(path, "PATH", "/tmp", PATTERN)
    with pytest.raises(ValueError):
        update_env.set_value(path, "APP_VALUE", "two words", PATTERN)
