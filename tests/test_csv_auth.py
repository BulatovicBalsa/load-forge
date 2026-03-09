"""
Tests for CSV-based multi-user authentication in load testing.
"""
import httpx
import pytest

from loadforge.parser.parse import parse_str
from loadforge.runtime.runner import run_test


DSL_CSV_AUTH = r'''
test "csv_auth_test" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "test_users.csv"
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

DSL_CSV_AUTH_CUSTOM_COLUMNS = r'''
test "csv_custom_columns" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "custom_users.csv"
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

DSL_CSV_NO_LOAD = r'''
test "csv_no_load" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
  }

  target #baseUrl

  auth login {
    file "test_users.csv"
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


def test_csv_auth_multiple_users(monkeypatch, tmp_path):
    """Test that CSV authentication loads multiple users and each gets their own token."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # Create CSV file with test users
    csv_file = tmp_path / "test_users.csv"
    csv_file.write_text(
        "username,password\n"
        "alice,pass123\n"
        "bob,secret456\n"
        "charlie,mypass789\n"
    )

    # Change to tmp directory so relative path resolves
    monkeypatch.chdir(tmp_path)

    model = parse_str(DSL_CSV_AUTH)

    # Track which users authenticated and their tokens
    auth_calls = []
    protected_calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        # Authentication requests
        if req.method == "POST" and str(req.url) == "https://auth.example.com/login":
            body = req.read().decode('utf-8')
            auth_calls.append(body)
            
            # Return unique token based on username
            if b"alice" in req.content:
                return httpx.Response(200, json={"token": "TOKEN_ALICE"})
            elif b"bob" in req.content:
                return httpx.Response(200, json={"token": "TOKEN_BOB"})
            elif b"charlie" in req.content:
                return httpx.Response(200, json={"token": "TOKEN_CHARLIE"})
            
            return httpx.Response(401, json={"error": "Invalid credentials"})

        # Protected endpoint requests
        if req.method == "GET" and "/protected" in str(req.url):
            auth_header = req.headers.get("Authorization", "")
            protected_calls.append(auth_header)
            
            # Verify bearer token is present
            if auth_header.startswith("Bearer TOKEN_"):
                return httpx.Response(200, json={"message": "Success"})
            return httpx.Response(403, json={"error": "Unauthorized"})

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport)

    # Verify results
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


def test_csv_auth_custom_column_names(monkeypatch, tmp_path):
    """Test CSV authentication with custom column names (not username/password)."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/token")

    # Create CSV with custom column names
    csv_file = tmp_path / "custom_users.csv"
    csv_file.write_text(
        "email,pass,tenant\n"
        "user1@test.com,pwd1,tenant-a\n"
        "user2@test.com,pwd2,tenant-b\n"
    )

    monkeypatch.chdir(tmp_path)
    model = parse_str(DSL_CSV_AUTH_CUSTOM_COLUMNS)

    auth_calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and "/token" in str(req.url):
            body = req.read().decode('utf-8')
            auth_calls.append(body)
            
            # Verify custom fields are present
            if b"email" in req.content and b"tenant" in req.content:
                if b"user1@test.com" in req.content:
                    assert b"tenant-a" in req.content
                    return httpx.Response(200, json={"access_token": "TOKEN_USER1"})
                elif b"user2@test.com" in req.content:
                    assert b"tenant-b" in req.content
                    return httpx.Response(200, json={"access_token": "TOKEN_USER2"})
            
            return httpx.Response(401)

        if req.method == "GET" and "/api/data" in str(req.url):
            if "Bearer TOKEN_" in req.headers.get("Authorization", ""):
                return httpx.Response(200)
            return httpx.Response(403)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert result.auth_success is True
    assert len(auth_calls) == 2


def test_csv_auth_without_load_block(monkeypatch, tmp_path):
    """Test CSV authentication without load block (single scenario execution)."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    csv_file = tmp_path / "test_users.csv"
    csv_file.write_text(
        "username,password\n"
        "testuser,testpass\n"
    )

    monkeypatch.chdir(tmp_path)
    model = parse_str(DSL_CSV_NO_LOAD)

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
    result = run_test(model, transport=transport)

    # Without load block, should use first CSV user
    assert result.failed == 0
    assert result.auth_success is True
    assert auth_count == 1


def test_csv_file_not_found(monkeypatch, tmp_path):
    """Test error handling when CSV file doesn't exist."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")
    monkeypatch.chdir(tmp_path)

    model = parse_str(DSL_CSV_AUTH)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    
    # Should raise FileNotFoundError
    with pytest.raises(FileNotFoundError) as exc_info:
        run_test(model, transport=transport)
    
    assert "test_users.csv" in str(exc_info.value)


def test_csv_missing_column_in_auth_body(monkeypatch, tmp_path):
    """Test error when CSV doesn't have columns referenced in auth body."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # CSV has different columns than auth body expects
    csv_file = tmp_path / "test_users.csv"
    csv_file.write_text(
        "email,pass\n"
        "alice@test.com,secret\n"
    )

    monkeypatch.chdir(tmp_path)
    model = parse_str(DSL_CSV_AUTH)  # Expects 'username' and 'password'

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": "TOKEN"})

    transport = httpx.MockTransport(handler)

    # Missing columns are now detected eagerly at CSV-load time
    with pytest.raises(ValueError) as exc_info:
        run_test(model, transport=transport)

    assert "missing required column" in str(exc_info.value).lower()
    assert "username" in str(exc_info.value)
    assert "password" in str(exc_info.value)


def test_csv_empty_values(monkeypatch, tmp_path):
    """Test error handling for CSV rows with empty values."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # CSV with empty password
    csv_file = tmp_path / "test_users.csv"
    csv_file.write_text(
        "username,password\n"
        "alice,pass123\n"
        "bob,\n"  # Empty password
    )

    monkeypatch.chdir(tmp_path)
    model = parse_str(DSL_CSV_AUTH)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    
    # Should raise ValueError about empty values
    with pytest.raises(ValueError) as exc_info:
        run_test(model, transport=transport)
    
    assert "Empty value" in str(exc_info.value)
    assert "password" in str(exc_info.value)


def test_csv_no_header_row(monkeypatch, tmp_path):
    """Test error handling for CSV without header row."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # Empty CSV file
    csv_file = tmp_path / "test_users.csv"
    csv_file.write_text("")

    monkeypatch.chdir(tmp_path)
    model = parse_str(DSL_CSV_AUTH)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    
    # Should raise ValueError about no data
    with pytest.raises(ValueError) as exc_info:
        run_test(model, transport=transport)
    
    assert "No user data" in str(exc_info.value) or "no header" in str(exc_info.value).lower()


def test_csv_round_robin_distribution(monkeypatch, tmp_path):
    """Test that users are distributed round-robin when users > CSV rows."""
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")

    # Only 2 users in CSV but requesting 4 virtual users
    csv_file = tmp_path / "test_users.csv"
    csv_file.write_text(
        "username,password\n"
        "alice,pass1\n"
        "bob,pass2\n"
    )

    monkeypatch.chdir(tmp_path)
    
    dsl_4_users = DSL_CSV_AUTH.replace("users 3", "users 4")
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
    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert result.auth_success is True
    
    # Should have 4 auth calls with round-robin pattern
    assert len(auth_usernames) == 4
    assert auth_usernames.count("alice") == 2  # indices 0, 2
    assert auth_usernames.count("bob") == 2    # indices 1, 3
