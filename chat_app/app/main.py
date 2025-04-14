from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, RootModel
from firebase import FirebaseDB
from copy import deepcopy
from typing import Dict, Any
from log import log
from config import get_prefix

database = FirebaseDB()
database.connect()

API_VERSION = '/api/v1'
PREFIX = get_prefix(API_VERSION)
log(f"Start HTTP server with prefix: {PREFIX}")
app = FastAPI(root_path=PREFIX)

origins = [
    "http://localhost:5173",  # localhost of FE app
    "https://zalophake.me"  # FE domain
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


def validate(body, key, type_origin, type_convert, error, required=False):
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

    # [3]: Try conversion to target type (to check number string like phone number)
    try:
        body[key] = type_convert(body[key])
    except ValueError:
        error["description"] = f"[Error] Cannot convert \"{key}\" to {type_convert}"
        log(error["description"])
        return False
    return True


@app.post("/api/auth/register", status_code=201)
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
    decoded_token = FirebaseDB.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "name", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")
    # Update the user's info
    user = database.update_user(decoded_token["uid"], phone_number=vRequest["phone_number"], display_name=vRequest["name"], password=vRequest["password"])

    # [3]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{decoded_token["uid"]}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if vResponse["body"]:
        log(f'[Error] User already exist in realtime database: {vResponse["body"]}')
        raise HTTPException(status_code=409, detail="[Error]: User already exist in database")
    # Insert user to DB if not existed
    database.insert(f'/User/{decoded_token["uid"]}', {"friends": [], "groups": []})

    return {"success": True, "user": vResponse["body"], "retoken": True}


@app.post("/api/auth/login", status_code=200)
async def login(request: Request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader
    log(f'[Debug] token: {vToken}')
    # [1]: Validate FE token from firebase OTP
    decoded_token = FirebaseDB.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # BE doesn't need to send token back, only need to verify FE token
    # FE refresh token is received directly from Firebase, invalid after logout
    return {"success": True}


@app.post("/api/auth/change-pass", status_code=200)
async def change_pass(request: Request):
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
    decoded_token = FirebaseDB.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Validate request body
    if not validate(vData, "old_password", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "new_password", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [3]: Check if user's password matches old password
    user = FirebaseDB.query_user_id(vRequest["phone_number"])
    log(f"[Debug] Queried user is: {user}")
    if not user.password == vRequest["old_password"]:
        log(f"[Error] Old password not matched")
        # return obscured error info to make it harder to attack
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # [3]: Update user's password
    user = database.update_user(password=vRequest["new_password"])
    return {"success": True, "user": user, "retoken": True}


@app.post("/api/auth/forgot-pass", status_code=200)
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
    
    # [1]: Validate request body
    if not validate(vData, "new_password", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [3]: Update user's password
    user = database.update_user(password=vRequest["new_password"])
    return {"success": True, "user": user, "retoken": True}


@app.get("/api/auth/profile", status_code=200)
async def profile(request: Request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader

    # [1]: Validate FE token from firebase OTP
    decoded_token = FirebaseDB.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")
    user = FirebaseDB.query_user_id(decoded_token["uid"])
    log(f"[Debug] Queried user is: {user}")

    # [2]: Check if user exist in realtimeDB
    vResponse = {}
    database.query(f'/User/{decoded_token["uid"]}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if not vResponse["body"]:
        log(f'[Error] User not found in realtime database')
        raise HTTPException(status_code=404, detail="[Error]: User not found in database")

    return {"user": user, "user_data": vResponse["body"]}