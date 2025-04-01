from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, RootModel
from firebase import FirebaseDB
from copy import deepcopy
from typing import Dict, Any
from log import log

database = FirebaseDB()
database.connect()
app = FastAPI()

def validate(body, key, type_origin, type_convert, error, required=False):
    # [1]: Check if body has key
    if (key not in body) and required:
        error["description"] = f"[Error] Can't find key {key}"
        log(error["description"])
        return False

    # [2]: Check type of request value
    if not isinstance(body[key], type_origin):
        error["description"] = f"[Error] Key {key} is not of type {type_origin}"
        log(error["description"])
        return False
    
    # [3]: Try conversion to target type (to check number string like phone number, otp)
    try:
        body[key] = type_convert(body[key])
    except ValueError:
        error["description"] = f"[Error] Cannot convert {key} to {type_convert}"
        log(error["description"])
        return False
    return True

# FastAPI route for login
@app.post("/api/auth/login")
async def login(request: Dict[Any, Any]):
    vData = deepcopy(request)  # Convert Pydantic model to dictionary
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password"    , str, str, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")
    
    # [2]: Check if user exist in DB
    vResponse = {}
    database.query(f"/User/{request["phone_number"]}", response=vResponse)
    log(f"[Debug] The response data is: {vResponse}")
    if not vResponse["body"]:
        log(f"[Debug] User not found in database")
        raise HTTPException(status_code=400, detail="[Error]: User not found in database")
    
    # TODO: Get token from database
    token = "1234"
    return {"success": True, "token": token, "user": vResponse}

@app.post("/api/auth/register")
async def register(request: Dict[Any, Any]):
    vData = deepcopy(request)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "name",         str, str, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password",     str, str, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "otp",          str, int, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    log(f"[Debug]: Converted data:\n {vData}")
    
    # [2]: Check if user exist in DB
    vResponse = {}
    database.query(f"/User/{request["phone_number"]}", response=vResponse)
    log(f"[Debug] The response data is: {vResponse}")
    if vResponse["body"]:
        log(f"[Debug] User already exist in database: {vResponse["body"]}")
        raise HTTPException(status_code=400, detail="[Error]: User already exist in database")
    
    # [3]: Insert user to DB if not existed
    database.insert(f"/User/{request["phone_number"]}", {"name": request["name"], "password": request["password"]})
    return {"success": True, "token": "1234", "user": "defaultUser"}
