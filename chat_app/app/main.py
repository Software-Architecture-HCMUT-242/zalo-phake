from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, RootModel
from firebase import FirebaseDB
from copy import deepcopy
from typing import Dict, Any
from log import log

database = FirebaseDB()
database.connect()
app = FastAPI()


@app.get("/")
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
    vResponse = {}
    database.query(f'/User/{request["phone_number"]}', response=vResponse)
    log(f"[Debug] The response data is: {vResponse}")
    if vResponse["body"]:
        log(f'[Debug] User already exist in database: {vResponse["body"]}')
        raise HTTPException(status_code=409, detail="[Error]: User already exist in database")

    # [3]: Validate FE token from firebase OTP
    decoded_token = database.verify_token(request["token"])
    if not decoded_token:
        log(f'[Debug] OTP token not valid: {decoded_token}')
        raise HTTPException(status_code=409, detail="[Error]: User already exist in database")

    # [4]: Insert user to DB if not existed
    database.insert(f'/User/{request["phone_number"]}', {"name": request["name"], "password": request["password"]})
    return {"success": True, "token": "1234", "user": "defaultUser"}


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
    vResponse = {}
    database.query(f'/User/{request["phone_number"]}', response=vResponse)
    log(f"[Debug] The response data is: {vResponse}")
    if not vResponse["body"]:
        log(f"[Debug] User phone number \"{request["phone_number"]}\" not found in database")
        # return obscured error info to make it harder to attack
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")
    
    # [3]: Validate password
    if vResponse["body"]["password"] != request["password"]:
        log(f"[Debug] User password \"{request["password"]}\" not match database \"{vResponse["body"]["password"]}\"")
        # return obscured error info to make it harder to attack
        raise HTTPException(status_code=401, detail="[Error]: Invalid credentials")

    # TODO: Get token from database
    token = "1234"
    return {"success": True, "token": token, "user": vResponse}


@app.post("/api/auth/logout", status_code=200)
async def register(request: Dict[Any, Any]):
    vData = deepcopy(request)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "token", str, int, vError, required=True):
        raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")

    # [2]: TODO validate token

    # [3]: Insert user to DB if not existed
    return {"success": True}
