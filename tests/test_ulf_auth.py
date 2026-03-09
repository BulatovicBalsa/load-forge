"""
Tests for .ulf (User List File) based multi-user authentication in load testing.
"""
import httpx
import pytest

from loadforge.cli import is_userlist_needed, main as cli_main, parse_args
from loadforge.parser.parse import parse_str, parse_file
from loadforge.runtime.runner import run_test


DSL_ULF_AUTH = r'''
test "ulf_auth_test" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "test_users.ulf"
    endpoint #authEndpoint
    method POST
    body {
      username = "${username}"
      password = "${password}"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/protected"
    expect status 200
  }

  load {
    users 3
    rampUp 0s
    duration 1s
  }
}
'''

DSL_ULF_AUTH_USERNAME_ONLY = r'''
test "ulf_username_only" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "test_users.ulf"
    endpoint #authEndpoint
    method POST
    body {
      username = "${username}"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/protected"
    expect status 200
  }

  load {
    users 2
    rampUp 0s
    duration 1s
  }
}
'''

DSL_ULF_NO_LOAD = r'''
test "ulf_no_load" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "test_users.ulf"
    endpoint #authEndpoint
    method POST
    body {
      username = "${username}"
      password = "${password}"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/protected"
    expect status 200
  }
}
'''

DSL_ULF_AUTH_BAD_PLACEHOLDER = r'''
test "ulf_bad_placeholder" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "test_users.ulf"
    endpoint #authEndpoint
    method POST
    body {
      email = "${email}"
      pass = "${pass}"
      tenant = "${tenant}"
    }
    format "$.access_token"
  }

  scenario "s" {
    request GET "/api/data"
    expect status 200
  }

  load {
    users 2
    rampUp 0s
    duration 1s
  }
}
'''


def test_ulf_auth_multiple_users(monkeypatch, tmp_path):
    """Test that .ulf authentication loads multiple users and each gets their own token."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text(
        "alice : pass123\n"
        "bob : secret456\n"
        "charlie : mypass789\n"
    )

    model = parse_str(DSL_ULF_AUTH)

    auth_calls = []
    protected_calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and str(req.url) == "https://auth.example.com/login":
            body = req.read().decode('utf-8')
            auth_calls.append(body)

            if b"alice" in req.content:
                return httpx.Response(200, json={"token": "TOKEN_ALICE"})
            elif b"bob" in req.content:
                return httpx.Response(200, json={"token": "TOKEN_BOB"})
            elif b"charlie" in req.content:
                return httpx.Response(200, json={"token": "TOKEN_CHARLIE"})

            return httpx.Response(401, json={"error": "Invalid credentials"})

        if req.method == "GET" and "/protected" in str(req.url):
            auth_header = req.headers.get("Authorization", "")
            protected_calls.append(auth_header)

            if auth_header.startswith("Bearer TOKEN_"):
                return httpx.Response(200, json={"message": "Success"})
            return httpx.Response(403, json={"error": "Unauthorized"})

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=ulf_file)

    assert result.failed == 0
    assert result.auth_success is True

    # Should have 3 auth calls (one per user)
    assert len(auth_calls) == 3
    assert any("alice" in call for call in auth_calls)
    assert any("bob" in call for call in auth_calls)
    assert any("charlie" in call for call in auth_calls)

    # Should have multiple protected calls with proper tokens
    assert len(protected_calls) > 0
    assert any("TOKEN_ALICE" in call for call in protected_calls)
    assert any("TOKEN_BOB" in call for call in protected_calls)
    assert any("TOKEN_CHARLIE" in call for call in protected_calls)


def test_ulf_auth_verifies_credentials_in_body(monkeypatch, tmp_path):
    """Test that username and password from .ulf are correctly interpolated into the auth body."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("testuser : s3cretP@ss!\n")

    model = parse_str(DSL_ULF_NO_LOAD)

    captured_payloads = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and "/login" in str(req.url):
            import json
            payload = json.loads(req.content)
            captured_payloads.append(payload)
            return httpx.Response(200, json={"token": "TOK"})

        if req.method == "GET" and "/protected" in str(req.url):
            if "Bearer TOK" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=ulf_file)

    assert result.failed == 0
    assert len(captured_payloads) == 1
    assert captured_payloads[0]["username"] == "testuser"
    assert captured_payloads[0]["password"] == "s3cretP@ss!"


def test_ulf_auth_without_load_block(monkeypatch, tmp_path):
    """Test .ulf authentication without load block (single scenario execution)."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("testuser : testpass\n")

    model = parse_str(DSL_ULF_NO_LOAD)

    auth_count = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal auth_count

        if req.method == "POST" and "/login" in str(req.url):
            auth_count += 1
            return httpx.Response(200, json={"token": "TOKEN_TEST"})

        if req.method == "GET" and "/protected" in str(req.url):
            if "Bearer TOKEN_TEST" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=ulf_file)

    assert result.failed == 0
    assert result.auth_success is True
    assert auth_count == 1


def test_ulf_file_not_found(monkeypatch, tmp_path):
    """Test error handling when .ulf file doesn't exist."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    missing_ulf = tmp_path / "test_users.ulf"

    model = parse_str(DSL_ULF_AUTH)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    with pytest.raises(FileNotFoundError) as exc_info:
        run_test(model, transport=transport, userlist_path=missing_ulf)

    assert "test_users.ulf" in str(exc_info.value)


def test_ulf_unsupported_placeholders(monkeypatch, tmp_path):
    """Test error when auth body references variables not available in .ulf format."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("alice : secret\n")

    model = parse_str(DSL_ULF_AUTH_BAD_PLACEHOLDER)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "TOKEN"})

    transport = httpx.MockTransport(handler)

    # Auth body uses ${email}, ${pass}, ${tenant} — none are provided by .ulf
    with pytest.raises(ValueError) as exc_info:
        run_test(model, transport=transport, userlist_path=ulf_file)

    err = str(exc_info.value).lower()
    assert "not available in .ulf format" in err


def test_ulf_empty_file(monkeypatch, tmp_path):
    """Test error handling for .ulf file with no entries."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("")

    model = parse_str(DSL_ULF_AUTH)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    with pytest.raises(ValueError) as exc_info:
        run_test(model, transport=transport, userlist_path=ulf_file)

    assert "No user entries" in str(exc_info.value)


def test_ulf_malformed_file(monkeypatch, tmp_path):
    """Test error handling for .ulf file with invalid syntax."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("this is not valid ulf syntax\n")

    model = parse_str(DSL_ULF_AUTH)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    with pytest.raises(ValueError) as exc_info:
        run_test(model, transport=transport, userlist_path=ulf_file)

    assert "Failed to parse" in str(exc_info.value)


def test_ulf_round_robin_distribution(monkeypatch, tmp_path):
    """Test that users are distributed round-robin when VUs > .ulf entries."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # Only 2 users in .ulf but requesting 4 virtual users
    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text(
        "alice : pass1\n"
        "bob : pass2\n"
    )

    dsl_4_users = DSL_ULF_AUTH.replace("users 3", "users 4")
    model = parse_str(dsl_4_users)

    auth_usernames = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and "/login" in str(req.url):
            body = req.read().decode('utf-8')
            if "alice" in body:
                auth_usernames.append("alice")
                return httpx.Response(200, json={"token": "TOKEN_ALICE"})
            elif "bob" in body:
                auth_usernames.append("bob")
                return httpx.Response(200, json={"token": "TOKEN_BOB"})
            return httpx.Response(401)

        if req.method == "GET" and "/protected" in str(req.url):
            if "Bearer TOKEN_" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=ulf_file)

    assert result.failed == 0
    assert result.auth_success is True

    # Should have 4 auth calls with round-robin pattern
    assert len(auth_usernames) == 4
    assert auth_usernames.count("alice") == 2  # indices 0, 2
    assert auth_usernames.count("bob") == 2    # indices 1, 3


def test_ulf_username_only_in_body(monkeypatch, tmp_path):
    """Test that .ulf works when only ${username} is used in auth body."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text(
        "alice : pass1\n"
        "bob : pass2\n"
    )

    model = parse_str(DSL_ULF_AUTH_USERNAME_ONLY)

    auth_calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and "/login" in str(req.url):
            import json
            payload = json.loads(req.content)
            auth_calls.append(payload)
            return httpx.Response(200, json={"token": f"TOKEN_{payload['username'].upper()}"})

        if req.method == "GET" and "/protected" in str(req.url):
            if "Bearer TOKEN_" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=ulf_file)

    assert result.failed == 0
    assert result.auth_success is True
    assert len(auth_calls) == 2
    # Body should only have username, not password
    for call in auth_calls:
        assert "username" in call
        assert "password" not in call


def test_ulf_special_characters_in_password(monkeypatch, tmp_path):
    """Test that passwords with special characters are parsed correctly."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("alice : P@ss!w0rd#2024\n")

    model = parse_str(DSL_ULF_NO_LOAD)

    captured_passwords = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and "/login" in str(req.url):
            import json
            payload = json.loads(req.content)
            captured_passwords.append(payload.get("password"))
            return httpx.Response(200, json={"token": "TOK"})

        if req.method == "GET" and "/protected" in str(req.url):
            if "Bearer TOK" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=ulf_file)

    assert result.failed == 0
    assert captured_passwords == ["P@ss!w0rd#2024"]


def test_ulf_multiple_entries_parsed(tmp_path):
    """Test that the textX grammar correctly parses multiple .ulf entries."""
    from loadforge.parser.metamodel import build_userlist_metamodel

    ulf_file = tmp_path / "users.ulf"
    ulf_file.write_text(
        "alice : pass1\n"
        "bob : pass2\n"
        "charlie : pass3\n"
    )

    mm = build_userlist_metamodel()
    model = mm.model_from_file(str(ulf_file))

    assert len(model.entries) == 3
    assert model.entries[0].username == "alice"
    assert model.entries[0].password == "pass1"
    assert model.entries[1].username == "bob"
    assert model.entries[1].password == "pass2"
    assert model.entries[2].username == "charlie"
    assert model.entries[2].password == "pass3"


def test_ulf_single_entry_parsed(tmp_path):
    """Test that a .ulf file with a single entry is parsed correctly."""
    from loadforge.parser.metamodel import build_userlist_metamodel

    ulf_file = tmp_path / "users.ulf"
    ulf_file.write_text("admin : hunter2\n")

    mm = build_userlist_metamodel()
    model = mm.model_from_file(str(ulf_file))

    assert len(model.entries) == 1
    assert model.entries[0].username == "admin"
    assert model.entries[0].password == "hunter2"


# ---------------------------------------------------------------------------
# CLI: --userlist-needed
# ---------------------------------------------------------------------------

DSL_WITH_ULF = r'''
test "with_ulf" {
  target "http://localhost"

  auth login {
    file "users.ulf"
    endpoint "/login"
    method POST
    body {
      username = "${username}"
      password = "${password}"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/ping"
    expect status 200
  }
}
'''

DSL_WITHOUT_ULF = r'''
test "no_ulf" {
  target "http://localhost"

  scenario "s" {
    request GET "/ping"
    expect status 200
  }
}
'''

DSL_AUTH_NO_FILE = r'''
test "auth_no_file" {
  target "http://localhost"

  auth login {
    endpoint "/login"
    method POST
    body {
      username = "static_user"
      password = "static_pass"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/ping"
    expect status 200
  }
}
'''


def test_is_userlist_needed_true():
    """is_userlist_needed returns True when auth login has a file field."""
    model = parse_str(DSL_WITH_ULF)
    assert is_userlist_needed(model) is True


def test_is_userlist_needed_false_no_auth():
    """is_userlist_needed returns False when there is no auth block."""
    model = parse_str(DSL_WITHOUT_ULF)
    assert is_userlist_needed(model) is False


def test_is_userlist_needed_false_auth_without_file():
    """is_userlist_needed returns False when auth exists but has no file field."""
    model = parse_str(DSL_AUTH_NO_FILE)
    assert is_userlist_needed(model) is False


def test_cli_userlist_needed_prints_true(tmp_path, capsys):
    """--userlist-needed prints 'true' for a .lf that uses file in auth."""
    lf_file = tmp_path / "test.lf"
    lf_file.write_text(DSL_WITH_ULF)

    ret = cli_main(["--userlist-needed", str(lf_file)])
    assert ret == 0
    assert capsys.readouterr().out.strip() == "true"


def test_cli_userlist_needed_prints_false(tmp_path, capsys):
    """--userlist-needed prints 'false' for a .lf without file in auth."""
    lf_file = tmp_path / "test.lf"
    lf_file.write_text(DSL_WITHOUT_ULF)

    ret = cli_main(["--userlist-needed", str(lf_file)])
    assert ret == 0
    assert capsys.readouterr().out.strip() == "false"


def test_cli_userlist_needed_false_for_static_auth(tmp_path, capsys):
    """--userlist-needed prints 'false' for auth login without file."""
    lf_file = tmp_path / "test.lf"
    lf_file.write_text(DSL_AUTH_NO_FILE)

    ret = cli_main(["--userlist-needed", str(lf_file)])
    assert ret == 0
    assert capsys.readouterr().out.strip() == "false"


def test_cli_errors_when_userlist_needed_but_not_provided(tmp_path, capsys):
    """CLI returns exit 1 when the .lf needs a .ulf but none is provided."""
    lf_file = tmp_path / "test.lf"
    lf_file.write_text(DSL_WITH_ULF)

    ret = cli_main([str(lf_file)])
    assert ret == 1
    err = capsys.readouterr().err
    assert "user list file" in err.lower() or ".ulf" in err.lower()


def test_cli_accepts_userlist_path(tmp_path):
    """CLI resolves the .ulf path from the third positional arg."""
    lf_file = tmp_path / "test.lf"
    lf_file.write_text(DSL_ULF_NO_LOAD)

    ulf_file = tmp_path / "test_users.ulf"
    ulf_file.write_text("alice : pass1\n")

    # parse_args should accept and resolve the userlist path
    opts = parse_args([str(lf_file), None, str(ulf_file)])
    assert opts.userlist == ulf_file.resolve()


def test_cli_userlist_file_not_found(tmp_path):
    """CLI exits with error when the provided .ulf path does not exist."""
    lf_file = tmp_path / "test.lf"
    lf_file.write_text(DSL_WITH_ULF)

    with pytest.raises(SystemExit) as exc_info:
        parse_args([str(lf_file), None, str(tmp_path / "missing.ulf")])

    assert exc_info.value.code != 0


def test_run_test_with_userlist_path(monkeypatch, tmp_path):
    """run_test uses userlist_path when provided, ignoring the name in the .lf file."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # .lf references "test_users.ulf" but we provide a different file via userlist_path
    model = parse_str(DSL_ULF_NO_LOAD)

    # Place the .ulf at a custom location (not where the .lf name points)
    custom_ulf = tmp_path / "custom_dir" / "my_users.ulf"
    custom_ulf.parent.mkdir(parents=True)
    custom_ulf.write_text("bob : secretpwd\n")

    captured_usernames = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and "/login" in str(req.url):
            import json
            payload = json.loads(req.content)
            captured_usernames.append(payload.get("username"))
            return httpx.Response(200, json={"token": "TOK"})

        if req.method == "GET" and "/protected" in str(req.url):
            if "Bearer TOK" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport, userlist_path=custom_ulf)

    assert result.failed == 0
    assert captured_usernames == ["bob"]


def test_run_test_no_userlist_not_needed():
    """run_test works without userlist_path when auth has no file field."""
    model = parse_str(DSL_WITHOUT_ULF)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport)

    assert result.failed == 0
