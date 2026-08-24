from httpx import ASGITransport, AsyncClient

from kira.api.app import create_app
from kira.db.session import get_session


class TestApiIsNotShadowed:
    async def test_health_still_answers(self, client):
        assert (await client.get("/v1/health")).status_code == 200

    async def test_unknown_api_route_is_a_404_not_the_app_shell(self, client):
        response = await client.get("/v1/nope")
        assert response.status_code == 404
        assert "<!doctype html>" not in response.text.lower()

    async def test_bundle_falls_back_only_for_client_routes(self, session, tmp_path):
        (tmp_path / "index.html").write_text("<!doctype html><title>Kira</title>")
        app = create_app(static_dir=tmp_path)

        async def override():
            yield session

        app.dependency_overrides[get_session] = override
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            deep_link = await client.get("/some/deep/link")
            unknown_api = await client.get("/v1/nope")

        assert deep_link.status_code == 200
        assert "<!doctype html>" in deep_link.text.lower()
        assert unknown_api.status_code == 404
        assert "<!doctype html>" not in unknown_api.text.lower()
