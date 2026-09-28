from fastapi.testclient import TestClient
from app.main import app

def test_health():
    with TestClient(app) as c:
        assert c.get('/api/health').json()['status']=='ok'
