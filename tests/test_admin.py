from eNMS import app
from eNMS.database.functions import fetch, fetch_all

from tests.conftest import check_pages


def test_authentication(base_client):
    for page in app.rbac["endpoints"]["GET"]:
        r = base_client.get(page)
        if page == "/login":
            assert r.status_code == 200
        else:
            assert r.status_code == 302 and "login" in r.location


def test_urls(user_client):
    for page in app.rbac["endpoints"]["GET"]:
        r = user_client.get(page, follow_redirects=True)
        assert r.status_code == 200
    r = user_client.get("/logout", follow_redirects=True)
    test_authentication(user_client)


@check_pages("table/user")
def test_user_management(user_client):
    for user in ("user1", "user2", "user3"):
        dict_user = {
            "form_type": "user",
            "name": user,
            "email": f"{user}@test.com",
            "group": "Admin",
            "password": user,
        }
        user_client.post("/update/user", data=dict_user)
    assert len(fetch_all("user")) == 4
    user1 = fetch("user", name="user1")
    user_client.post("/delete_instance/user/{}".format(user1.id))
    assert len(fetch_all("user")) == 3
