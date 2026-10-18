import requests

if __name__ == "__main__":
    # 1. Login with demo user
    login_res = requests.post("http://localhost:8000/api/v1/auth/login", json={
        "identifier": "usr_demo0001",
        "password": "DemoPass1234!"
    })
    print("Login status:", login_res.status_code, login_res.json().get("ok"))
    token = login_res.json()["data"]["token"]

    # 2. Check an existing itinerary or session plan
    test_itin_id = "session_plan_agt_0733b17c"
    review_res = requests.post(
        f"http://localhost:8000/api/v1/itineraries/{test_itin_id}/booking-review",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "itinerary_id": test_itin_id,
            "itinerary_version": 1,
            "travellers": [{"display_name": "Primary Traveller", "traveller_role": "adult"}]
        }
    )
    print("Review response with auth:", review_res.status_code, review_res.text[:300])

    # 3. Test without auth (guest)
    guest_res = requests.post(
        f"http://localhost:8000/api/v1/itineraries/{test_itin_id}/booking-review",
        json={
            "itinerary_id": test_itin_id,
            "itinerary_version": 1,
            "travellers": [{"display_name": "Guest Traveller", "traveller_role": "adult"}]
        }
    )
    print("Review response guest:", guest_res.status_code, guest_res.text[:300])
