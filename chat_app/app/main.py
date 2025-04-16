from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, RootModel
from firebase import FirebaseDB
from copy import deepcopy
from typing import Dict, Any
from log import log
from config import get_prefix
import hashlib
import phonenumbers
from phonenumbers import geocoder, carrier, is_valid_number

database = FirebaseDB()
database.connect()

API_VERSION = '/api/v1'
PREFIX = get_prefix(API_VERSION)
log(f"Start HTTP server with prefix: {PREFIX}")
app = FastAPI(root_path=PREFIX)

origins = [
    "https://zalophake.me",  # FE domain,
    "http://localhost:5173",  # localhost of FE app
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
def ping():
    return {"message": "pong"}

def hash(phone_number):
    return hashlib.sha256(phone_number.encode("utf-8")).hexdigest()

def validate(body, key, type_origin, error, required=False):
    # [1]: Check if body has key
    if (key not in body) and required:
        error["description"] = f"[Error] Can't find key \"{key}\""
        log(error["description"])
        return False

    # [2]: Check type of request value
    if not isinstance(body[key], type_origin):
        error["description"] = f"[Error] Key \"{key}\" is not of type {type_origin}"
        log(error["description"])
        return False

    return True


@app.post("/auth/register", status_code=201)
async def register(request: Request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader
    vRequest = await request.json()
    vData = deepcopy(vRequest)
    vError = {}

    # [1]: Validate FE token from firebase OTP
    # NOTE: After FE send OTP back, firebase will create a user and send this user's token back
    # this user will have empty keys like name, password, ... Only uid will be init
    decoded_token = database.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Validate request body
    if not validate(vData, "phone_number", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "name", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")
    parsed = {}
    try:
        parsed = phonenumbers.parse(vRequest["phone_number"])
        log(f'[Debug] Parsed phone number: {parsed}')
    except Exception as e:
        log(f'[Error] Parse phone number failed: {vRequest["phone_number"]}')
        raise HTTPException(status_code=400, detail="[Error]: Invalid phone number")
    if not phonenumbers.is_valid_number(parsed):
        log(f'[Error] Invalid phone number: {vRequest["phone_number"]}')
        raise HTTPException(status_code=400, detail="[Error]: Invalid phone number")

    # [3]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{vRequest["phone_number"]}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if vResponse["body"]:
        log(f'[Error] User already exist in realtime database: {vResponse["body"]}')
        raise HTTPException(status_code=409, detail="[Error]: User already exist in database")

    # [4]: Insert user and hashed password to DB if not existed
    password_hash = hash(vRequest["password"])
    database.insert(f'/User/{vRequest["phone_number"]}', {
        "password": password_hash,
        "name": vRequest["name"],
        "profile_pic": None,
        "friends": [],
        "groups": []})

    return {"success": True}


@app.post("/auth/login", status_code=200)
async def login(request: Request):
    vRequest = await request.json()
    vData = deepcopy(vRequest)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")
    parsed = {}
    try:
        parsed = phonenumbers.parse(vRequest["phone_number"])
        log(f'[Debug] Parsed phone number: {parsed}')
    except Exception as e:
        log(f'[Error] Parse phone number failed: {vRequest["phone_number"]}')
        raise HTTPException(status_code=400, detail="[Error]: Invalid phone number")
    if not phonenumbers.is_valid_number(parsed):
        log(f'[Error] Invalid phone number: {vRequest["phone_number"]}')
        raise HTTPException(status_code=400, detail="[Error]: Invalid phone number")

    # [2]: Check if user exist in Authen
    user = database.query_user_by_phone_number(vRequest["phone_number"])
    if not user:
        log(f'[Error] Phone number not found')
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # [3]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{vRequest["phone_number"]}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if not vResponse["body"]:
        log(f'[Error] User not found')
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # [4]: Check if password matches user
    password_hash = hash(vRequest["password"])
    if not vResponse["body"]["password"] == password_hash:
        log(f'[Error] Password not matched: \"{vResponse["body"]["password"]}\" | \"{vRequest["password"]}\"')
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # BE doesn't need to send token back, only need to verify FE token
    # FE refresh token is received directly from Firebase, invalid after logout
    return {"success": True}


@app.post("/auth/change-pass", status_code=200)
async def change_pass(request: Request):
    vRequest = await request.json()
    vData = deepcopy(vRequest)
    vError = {}

    # [1]: Validate request body
    if not validate(vData, "phone_number", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "old_password", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "new_password", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [2]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{vRequest["phone_number"]}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if not vResponse["body"]:
        log(f'[Error] User not found')
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # [3]: Check if user's password matches old password
    password_hash = hashlib.sha256(vRequest["old_password"].encode("utf-8")).hexdigest()
    if not vResponse["body"]["password"] == password_hash:
        log(f"[Error] Old password not matched")
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # [4]: Update user's password
    password_hash = hash(vRequest["new_password"])
    database.update(f'/User/{vRequest["phone_number"]}/password', password_hash)
    return {"success": True}


@app.post("/auth/forgot-pass", status_code=200)
async def forgot_pass(request: Request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader
    vRequest = await request.json()
    vData = deepcopy(vRequest)
    vError = {}

    # [1]: Validate FE token from firebase OTP
    decoded_token = database.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")
    phone_number = {}
    try:
        phone_number = decoded_token.get("phone_number")
        log(f'[Debug] Token phone number: {phone_number}')
    except Exception as e:
        log(f'[Error] Token get phone number failed')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Validate request body
    if not validate(vData, "new_password", str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [3]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{phone_number}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if not vResponse["body"]:
        log(f'[Error] User not found')
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # [4]: Update user's password
    password_hash = hash(vRequest["new_password"])
    database.update(f'/User/{phone_number}/password', password_hash)
    return {"success": True}


@app.get("/auth/profile", status_code=200)
async def profile(request: Request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader

    # [1]: Validate FE token from firebase OTP
    decoded_token = database.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")
    user = database.query_user_id(decoded_token["uid"])
    log(f"[Debug] Queried user is: {user}")
    phone_number = {}
    try:
        phone_number = decoded_token.get("phone_number")
        log(f'[Debug] Token phone number: {phone_number}')
    except Exception as e:
        log(f'[Error] Token get phone number failed')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{phone_number}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if not vResponse["body"]:
        log(f'[Error] User not found in realtime database')
        raise HTTPException(status_code=404, detail="[Error]: User not found in database")

    return {"user": user, "user_data": vResponse["body"]}

@app.post("/auth/update-profile", status_code=200)
async def update_profile(request: Request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader
    vRequest = await request.json()
    vData = deepcopy(vRequest)
    vError = {}

    # [1]: Validate FE token from firebase OTP
    decoded_token = database.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")
    phone_number = {}
    try:
        phone_number = decoded_token.get("phone_number")
        log(f'[Debug] Token phone number: {phone_number}')
    except Exception as e:
        log(f'[Error] Token get phone number failed')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Validate request body
    if not validate(vData, "name", str, vError, required=False):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "profile_pic", str, vError, required=False):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [3]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{phone_number}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if vResponse["body"]:
        log(f'[Error] User already exist in realtime database: {vResponse["body"]}')
        raise HTTPException(status_code=409, detail="[Error]: User already exist in database")

    # [4]: Update user and hashed password to DB if not existed
    database.update(f'/User/{phone_number}/name', vRequest["name"])
    database.update(f'/User/{phone_number}/profile_pic', vRequest["profile_pic"])
    return {"success": True}