"""Hermetic check for parent_session_id: persistence + .env injection + 404.

Runs the real FastAPI app via TestClient (no network/port). Exercises the
sessions router, mock DB, and the PARENT_SESSION_ID/.env writing path.
"""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

API = "/api/v1/sessions"
AGENT = "agent-claude-code-001"


def main() -> None:
    with TestClient(app) as client, tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        template_dir = tmp / "tpl"
        template_dir.mkdir()
        (template_dir / "CLAUDE.md").write_text("dummy template\n", encoding="utf-8")
        child_wd = tmp / "child"  # must NOT exist (copy target)

        # 1) parent session
        r = client.post(API, json={"agent_id": AGENT})
        assert r.status_code == 201, (r.status_code, r.text)
        parent_id = r.json()["id"]
        print("parent created:", parent_id)

        # 2) child spawned by parent
        r = client.post(API, json={
            "agent_id": AGENT,
            "working_dir": str(child_wd),
            "template_dir": str(template_dir),
            "env": "GATEWAY_URL=http://localhost:12598",
            "parent_session_id": parent_id,
        })
        assert r.status_code == 201, (r.status_code, r.text)
        child = r.json()
        print("child created:", child["id"], "parent_session_id=", child["parent_session_id"])
        assert child["parent_session_id"] == parent_id, child

        # 3) .env injection
        env_text = (child_wd / ".env").read_text(encoding="utf-8")
        print("---- child .env ----\n" + env_text + "--------------------")
        assert f"PARENT_SESSION_ID={parent_id}" in env_text, env_text
        assert f"MY_SESSION_ID={child['id']}" in env_text, env_text
        assert "GATEWAY_URL=http://localhost:12598" in env_text, env_text
        # injected lines must come after operator env so they win on `set -a`
        assert env_text.index("GATEWAY_URL") < env_text.index("PARENT_SESSION_ID")

        # 4) unknown parent -> 404
        r = client.post(API, json={"agent_id": AGENT, "parent_session_id": "does-not-exist"})
        assert r.status_code == 404, (r.status_code, r.text)
        print("unknown parent -> 404 OK:", r.json()["detail"])

        # 5) GET child round-trips the field
        r = client.get(f"{API}/{child['id']}")
        assert r.status_code == 200 and r.json()["parent_session_id"] == parent_id

    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
