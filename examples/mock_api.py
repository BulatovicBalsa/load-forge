from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="LoadForge Example Mock API")


class LoginPayload(BaseModel):
    username: str
    password: str


USERS = {
    1: {
        "id": 1,
        "name": "Alice",
        "age": 30,
        "is_active": True,
        "address": {"city": "Belgrade", "country": "RS"},
        "tags": ["python", "qa", "load-testing"],
        "deleted_at": None,
        "email": "alice@example.com",
    }
}

CATALOG = {
    "phone": [
        {"id": 101, "name": "iPhone 14"},
        {"id": 102, "name": "Galaxy S23"},
        {"id": 103, "name": "Pixel 8"},
    ],
    "laptop": [
        {"id": 201, "name": "MacBook Air"},
        {"id": 202, "name": "ThinkPad X1"},
    ],
}


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
def auth_login(payload: LoginPayload) -> dict[str, str]:
    print(payload)
    if payload.username in ["alice@example.com", "charlie@example.com", "bob@example.com", "admin"] and payload.password == "admin":
    # if payload.username == "admin" and payload.password == "admin":
        return {"access_token": "demo-token"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/users/{user_id}")
def get_user(user_id: int) -> dict:
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/users")
def list_users(q: str = "") -> dict[str, list[dict]]:
    if q == "nonexistent":
        return {"results": []}
    return {"results": list(USERS.values())}


@app.get("/catalog/search")
def catalog_search(q: str = "") -> dict:
    items = CATALOG.get(q, [])
    return {
        "results": items,
        "count": len(items),
        "data": {"items": items},
    }
