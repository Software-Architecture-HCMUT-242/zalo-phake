from fastapi import FastAPI, HTTPException, status
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
    "https://zalophake.me"  # placeholder for FE domain
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
async def register(request: Dict[Any, Any]):
    vData = deepcopy(request)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "name", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password", str, str, vError, required=True): 
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [2]: Check if user exist in DB
    user = database.query_user_by_phone_number(request["phone_number"])
    log(f"[Debug] Queried user is: {user}")
    if user:
        log(f'[Error] User already exist in database')
        raise HTTPException(status_code=409, detail="[Error]: User already exist in database")

    # [3]: Validate FE token from firebase OTP
    decoded_token = database.verify_token(request["token"])
    if not decoded_token:
        log(f'[Error] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=401, detail="[Error]: OTP token not valid")

    # [4]: Insert user to DB if not existed
    user = database.create_user(phone_number=request["phone_number"], password=request["password"])
    return {"success": True, "token": "1234", "user": user}


@app.post("/api/auth/login", status_code=200)
async def login(request: Dict[Any, Any]):
    vData = deepcopy(request)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password", str, str, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [2]: Check if user exist in DB
    user = database.query_user_by_phone_number(request["phone_number"])
    log(f"[Debug] Queried user is: {user}")
    if not user:
        log(f"[Debug] User phone number \"{request["phone_number"]}\" not found in database")
        # return obscured error info to make it harder to attack
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")
    
    # [3]: Validate password
    if user["password"] != request["password"]:
        log(f"[Debug] User password \"{request["password"]}\" not match database \"{user["password"]}\"")
        # return obscured error info to make it harder to attack
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # BE doesn't need to send token back, only need to verify FE token
    # FE refresh token is received directly from Firebase, invalid after logout
    return {"success": True, "user": user}


# @app.post("/api/auth/logout", status_code=200)
# async def register(request: Dict[Any, Any]):
#     vData = deepcopy(request)
#     vError = {}
#     # [1]: Validate request body
#     if not validate(vData, "token", str, int, vError, required=True):
#         raise HTTPException(status_code=400, detail=vError["description"])
#     log(f"[Debug]: Converted data:\n {vData}")

#     # [2]: TODO validate token

#     # [3]: Insert user to DB if not existed
#     return {"success": True}
