import os
import tempfile

os.environ.setdefault("JALSETU_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["ADMIN_EMAIL"] = "admin@jalsetu.test"
os.environ["ADMIN_PASSWORD"] = "correct-horse-battery"
os.environ["JALSETU_WRITE_LIMIT"] = "100000"
os.environ["JALSETU_LOGIN_LIMIT"] = "100000"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("JALSETU_DEMO", None)

import io  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import main  # noqa: E402


@pytest.fixture(scope="session")
def c():
    return TestClient(main.app)


def jpeg(w=3000, h=4000):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (80, 110, 130)).save(b, "JPEG")
    return b.getvalue()


def _account(c, role, org=None):
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post("/api/auth/register", json={"email": email, "password": "long-enough-pass", "name": role.title(), "role": role,
                                           "organization": org})
    assert r.status_code == 201, r.text
    return {"authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


@pytest.fixture(scope="session")
def admin(c):
    r = c.post("/api/auth/login", json={"email": "admin@jalsetu.test", "password": "correct-horse-battery"})
    assert r.status_code == 200, r.text
    return {"authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def citizen(c):
    return _account(c, "citizen")[0]


@pytest.fixture()
def org(c):
    return _account(c, "organization", "Lakeview Apartments")[0]


@pytest.fixture()
def org2(c):
    return _account(c, "organization", "Other Org")[0]
