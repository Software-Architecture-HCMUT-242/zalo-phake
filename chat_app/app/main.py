from fastapi import FastAPI, HTTPException, status, Request, Query
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

def validate_request_body(body, key, type_origin, required=False):
    # [1]: Check if body has key
    if (key not in body) and required:
        log(f"[Error] Can't find key \"{key}\"")
        raise HTTPException(status_code=400, detail=f"[Error] Can't find key \"{key}\"")

    # [2]: Check type of request value
    if not isinstance(body[key], type_origin):
        log(f"[Error] Key \"{key}\" is not of type {type_origin}")
        raise HTTPException(status_code=400, detail=f"[Error] Key \"{key}\" is not of type {type_origin}")

    return

def validate_header(request):
    vHeader = request.headers.get("Authorization")
    if not vHeader:
        log(f'[Error] Authorization header not found')
        raise HTTPException(status_code=400, detail="[Error]: Authorization header not found")
    # Extract the token (assuming it's in the format 'Bearer <token>')
    vToken = vHeader.split(" ")[1] if "Bearer" in vHeader else vHeader

    # [1]: Validate FE token from firebase OTP
    # NOTE: After FE send OTP back, firebase will create a user and send this user's token back
    # this user will have empty keys like name, password, ... Only uid will be init
    decoded_token = database.verify_token(vToken)
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [2]: Check if the token has phone number
    phone_number = {}
    try:
        phone_number = str(decoded_token.get("phone_number"))
        log(f'[Debug] Token phone number: {phone_number}')
    except Exception as e:
        log(f'[Error] Token get phone number failed')
        raise HTTPException(status_code=401, detail="[Error]: OTP token get phone number failed")

    return decoded_token, phone_number

def validate_phone_str(phone_number_str):
    parsed  = {}
    # [1]: Try parsing the phone string
    try:
        parsed = phonenumbers.parse(phone_number_str)
        log(f'[Debug] Parsed phone number: {parsed}')
    except Exception as e:
        log(f'[Error] Parse phone number failed: {phone_number_str}')
        raise HTTPException(status_code=400, detail=f"[Error]: Can't parse phone number: {phone_number_str}")
    # [2]: Check if the parsed phone string is a valid phone number
    if not phonenumbers.is_valid_number(parsed):
        log(f'[Error] Invalid phone number: {phone_number_str}')
        raise HTTPException(status_code=400, detail=f"[Error]: Invalid phone number: {phone_number_str}")
    return

def validate_realtimeDB_user_existed(user):
    vResponse = {}
    # Query user from realtime DB and check if data existed
    database.query(f'/User/{user}', response=vResponse)
    log(f"[Debug] The realtimeDB data is: {vResponse}")
    if not vResponse["body"]:
        log(f'[Error] Phone number {user} not found in realtimeDB')
        raise HTTPException(status_code=401, detail=f"[Error]: Phone number {user} not found in realtimeDB")
    return vResponse

@app.post("/auth/register", status_code=201)
async def register(request: Request):
    vRequest = await request.json()

    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Validate request body
    validate_request_body(vRequest, "phone_number", str, required=True)
    validate_request_body(vRequest, "name", str, required=True)
    validate_request_body(vRequest, "password", str, required=True)
    log(f'[Debug] Validate the phone number: {vRequest["phone_number"]}')
    validate_phone_str(vRequest["phone_number"])

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
        "profile_pic": "",
        "friends": {},
        "groups": {}})

    return {"success": True}


@app.post("/auth/login", status_code=200)
async def login(request: Request):
    vRequest = await request.json()

    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Validate request body
    validate_request_body(vRequest, "phone_number", str, required=True)
    validate_request_body(vRequest, "password", str, required=True)
    log(f'[Debug] Validate the phone number: {vRequest["phone_number"]}')
    validate_phone_str(vRequest["phone_number"])
    
    # [3] Check if phone number matches token
    if not phone_number == vRequest["phone_number"]:
        log(f'[Error] Phone number not matched token: {phone_number} | {vRequest["phone_number"]}')
        raise HTTPException(status_code=400, detail="[Error]: Phone number not matched token")

    # [4]: Check if user exist in Authen
    user = database.query_user_by_phone_number(vRequest["phone_number"])
    if not user:
        log(f'[Error] Phone number not found')
        raise HTTPException(status_code=401, detail="[Error]: Phone number not found in Authen")

    # [5]: Check if user exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(vRequest["phone_number"])

    # [6]: Check if password matches user
    password_hash = hash(vRequest["password"])
    if not vResponse["body"]["password"] == password_hash:
        log(f'[Error] Password not matched: \"{vResponse["body"]["password"]}\" | \"{vRequest["password"]}\"')
        raise HTTPException(status_code=401, detail="[Error]: Password not matched")

    # BE doesn't need to send token back, only need to verify FE token
    # FE refresh token is received directly from Firebase, invalid after logout
    return {"success": True}


@app.post("/auth/change-pass", status_code=200)
async def change_pass(request: Request):
    vRequest = await request.json()

    # [1]: Validate request body
    validate_request_body(vRequest, "phone_number", str, required=True)
    validate_request_body(vRequest, "old_password", str, required=True)
    validate_request_body(vRequest, "new_password", str, required=True)
    log(f'[Debug] Validate the phone number: {vRequest["phone_number"]}')
    validate_phone_str(vRequest["phone_number"])

    # [2]: Check if user exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(vRequest["phone_number"])

    # [3]: Check if user's password matches old password
    password_hash = hashlib.sha256(vRequest["old_password"].encode("utf-8")).hexdigest()
    if not vResponse["body"]["password"] == password_hash:
        log(f"[Error] Old password not matched")
        raise HTTPException(status_code=401, detail="[Error]: Old password not matched")

    # [4]: Update user's password
    password_hash = hash(vRequest["new_password"])
    database.update(f'/User/{vRequest["phone_number"]}/password', password_hash, response={})
    return {"success": True}


@app.post("/auth/forgot-pass", status_code=200)
async def forgot_pass(request: Request):
    vRequest = await request.json()

    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Validate request body
    validate_request_body(vRequest, "new_password", str, required=True)
    
    # [3]: Check if user exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(phone_number)

    # [4]: Update user's password
    password_hash = hash(vRequest["new_password"])
    database.update(f'/User/{phone_number}/password', password_hash, response={})
    return {"success": True}


@app.get("/auth/profile", status_code=200)
async def profile(request: Request):
    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Query user in Authen
    user = database.query_user_id(decoded_token["uid"])
    log(f"[Debug] Queried user is: {user}")

    # [3]: Check if user exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(phone_number)

    return {"user": user, "user_data": vResponse["body"]}


@app.post("/auth/update-profile", status_code=200)
async def update_profile(request: Request):
    vRequest = await request.json()

    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Validate request body
    validate_request_body(vRequest, "name", str, required=False)
    validate_request_body(vRequest, "profile_pic", str, required=False)

    # [3]: Check if user exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(phone_number)

    # [4]: Update user and hashed password to DB
    if "name" in vRequest: database.insert(f'/User/{phone_number}/name', vRequest["name"])
    if "profile_pic" in vRequest: database.insert(f'/User/{phone_number}/profile_pic', vRequest["profile_pic"])
    return {"success": True}


@app.post("/auth/search-phone", status_code=200)
async def contact(request: Request):
    vRequest = await request.json()

    # [1]: Validate request body
    validate_request_body(vRequest, "phone_number", str, required=True)
    log(f'[Debug] Validate the phone number: {vRequest["phone_number"]}')
    validate_phone_str(vRequest["phone_number"])

    # [2]: Check if phone number exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(vRequest["phone_number"])

    # [3]: Filter response keys
    vResponseKeys = ["name", "profile_pic"]
    response = {key: value for key, value in vResponse["body"].items() if key in vResponseKeys}
    return {"user_data": response}


@app.post("/auth/send-invite", status_code=200)
async def send_invite(request: Request):
    vRequest = await request.json()

    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Validate request body
    validate_request_body(vRequest, "invite_phone_number", str, required=True)
    log(f'[Debug] Validate the invited phone number: {vRequest["invite_phone_number"]}')
    validate_phone_str(vRequest["invite_phone_number"])

    # [3]: Check if phone number exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(phone_number)

    # [4]: Check if invited phone number is different from host phone number
    if vRequest["invite_phone_number"] == phone_number:
        log(f'[Error] Invited number cannot be the same as host number: {phone_number}')
        raise HTTPException(status_code=400, detail=f'[Error] Invited number cannot be the same as host number: {phone_number}')

    # [5]: Check if invited phone number exist in realtimeDB
    vResponseInv = validate_realtimeDB_user_existed(vRequest["invite_phone_number"])

    # [6]: Filter invite keys for inviting number
    vInvKeys = ["name", "profile_pic"]
    vInvite = {key: value for key, value in vResponse["body"].items() if key in vInvKeys}
    log(f"[Debug] The inviting phone_number's data is: {vInvite}")

    # [7]: Update invited number's invites
    database.insert(f'/User/{vRequest["invite_phone_number"]}/invites/{phone_number}', vInvite)
    return {"success": True}


@app.post("/auth/accept-invite", status_code=200)
async def accept_invite(request: Request):
    vRequest = await request.json()

    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Validate request body
    validate_request_body(vRequest, "accept_phone_number", str, required=True)
    log(f'[Debug] Validate the accepted phone number: {vRequest["accept_phone_number"]}')
    validate_phone_str(vRequest["accept_phone_number"])

    # [3]: Check if phone number exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(phone_number)


    # [4]: Check if accepted phone number is different from host phone number
    if vRequest["accept_phone_number"] == phone_number:
        log(f'[Error] accepted number cannot be the same as host number: {phone_number}')
        raise HTTPException(status_code=400, detail=f'[Error] accepted number cannot be the same as host number: {phone_number}')

    # [5]: Check if accepted phone number exist in this user's invites
    if "invites" not in vResponse["body"]:
        log(f'[Error] Invites not found in realtime database')
        raise HTTPException(status_code=404, detail=f"Invites not found in realtime database")
    if vRequest["accept_phone_number"] not in vResponse["body"]["invites"]:
        log(f'[Error] Invite for {vRequest["accept_phone_number"]} not found in realtime database')
        raise HTTPException(status_code=404, detail=f'Invite for {vRequest["accept_phone_number"]} not found in realtime database')

    # [6]: Check if accepted phone number exist in realtimeDB
    vResponseAcc = validate_realtimeDB_user_existed(vRequest["accept_phone_number"])

    # [7]: Filter keys for both users
    vUserKeys = ["name", "profile_pic"]
    vUser = {key: value for key, value in vResponse["body"].items() if key in vUserKeys}
    vUserAcc = {key: value for key, value in vResponseAcc["body"].items() if key in vUserKeys}
    log(f"[Debug] The accepted phone_number's data is: {vUserAcc}")

    # [8]: Update user's friends
    database.insert(f'/User/{phone_number}/friends/{vRequest["accept_phone_number"]}', vUserAcc)

    # [9]: Update accepted number's friends
    database.insert(f'/User/{vRequest["accept_phone_number"]}/friends/{phone_number}', vUser)

    # [10]: Remove accepted invitation from host
    vRep = {}
    database.delete(f'/User/{phone_number}/invites/{vRequest["accept_phone_number"]}', response=vRep)
    return {"success": True}


@app.get("/auth/contacts", status_code=200)
async def contacts(request: Request):
    # [1]: Validate FE header token from firebase OTP
    decoded_token, phone_number = validate_header(request=request)

    # [2]: Check if user exist in realtimeDB
    vResponse = validate_realtimeDB_user_existed(phone_number)

    # [3]: Check if user realtimeDB has contacts (friends)
    if "friends" not in vResponse["body"]:
        log(f'[Debug] User {phone_number} has no key \"friends\"')
        return {"contacts": {}}

    return {"contacts": vResponse["body"]['friends']}
