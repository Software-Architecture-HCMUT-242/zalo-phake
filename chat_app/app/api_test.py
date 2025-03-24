from fastapi.testclient import TestClient
import json

from main import app

client = TestClient(app)


def test_login():
    # Return 200
    vData = json.dumps({"phone_number": "1234567890", "password": "abcdefgh"})
    vResponse = client.post('/api/auth/login', data=vData, headers={"Content-Type": "application/json"},)
    assert vResponse.status_code == 200
    assert vResponse.json() == {
        "token": "1234",
        "user": "defaultUser",
        "success": True
    }
    # Return 400 (invalid phone number)
    vData = json.dumps({"phone_number": "abc123", "password": "abcdefgh"})
    response = client.post('/api/auth/login', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Cannot convert phone_number to {int}"}
    # Return 400 (invalid password)
    vData = json.dumps({"phone_number": "1234567890", "password": 123})
    response = client.post('/api/auth/login', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Key password is not of type {str}"}

def test_register(): #TODO: Add logic check, database check after implement firebase
    """Test the home route."""
    # Return 200
    vData = json.dumps({"phone_number": "1234567890", "password": "abcdefgh", "name": "TestUser", "otp": "123456"})
    response = client.post('/api/auth/register', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 200
    assert response.json() == {
        "token": "1234",
        "user": "defaultUser",
        "success": True
    }
    # Return 400 (invalid phone number)
    vData = json.dumps({"phone_number": 123, "password": "abcdefgh", "name": "TestUser", "otp": "123456"})
    response = client.post('/api/auth/register', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Key phone_number is not of type {str}"}
    # Return 400 (password not found)
    vData = json.dumps({"phone_number": "1234567890", "name": "TestUser", "otp": "123456"})
    response = client.post('/api/auth/register', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Can't find key password"}
    # Return 400 (invalid name)
    vData = json.dumps({"phone_number": "1234567890", "password": "abcdefgh", "name": None, "otp": "123456"})
    response = client.post('/api/auth/register', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Key name is not of type {str}"}
    # Return 400 (invalid otp)
    vData = json.dumps({"phone_number": "1234567890", "password": "abcdefgh", "name": "TestUser", "otp": "abcdef"})
    response = client.post('/api/auth/register', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Cannot convert otp to {int}"}

def test_send_otp(): #TODO: Add logic check, database check after implement firebase
    """Test the home route."""
    # Return 200
    vData = json.dumps({"phone_number": "1234567890"})
    response = client.post('/api/auth/send-otp', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 200
    assert response.json() == {"success": False}
    # Return 400 (invalid phone number)
    vData = json.dumps({})
    response = client.post('/api/auth/send-otp', data=vData, headers={"Content-Type": "application/json"},)
    assert response.status_code == 400
    assert response.json() == {"detail": f"[Error] Can't find key phone_number"}