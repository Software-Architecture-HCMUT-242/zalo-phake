from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, RootModel
from firebase import FirebaseDB
from copy import deepcopy
from typing import Dict, Any

database = FirebaseDB()
database.connect()
app = FastAPI()

def validate(body, key, type_origin, type_convert, error, required=False):
    # [1]: Check if body has key
    if (key not in body) and required:
        error["description"] = f"[Error] Can't find key {key}"
        print(error["description"])
        return False

    # [2]: Check type of request value
    if not isinstance(body[key], type_origin):
        error["description"] = f"[Error] Key {key} is not of type {type_origin}"
        print(error["description"])
        return False
    
    # [3]: Try conversion to target type (to check number string like phone number, otp)
    try:
        body[key] = type_convert(body[key])
    except ValueError:
        error["description"] = f"[Error] Cannot convert {key} to {type_convert}"
        print(error["description"])
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
    print(f"[Debug]: Converted data:\n {vData}")
    
    # Return successful response
    return {"success": True, "token": "1234", "user": "defaultUser"}

@app.post("/api/auth/register")
async def register(request: Dict[Any, Any]):
    vData = deepcopy(request)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "name",         str, str, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "password",     str, str, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    if not validate(vData, "otp",          str, int, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    print(f"[Debug]: Converted data:\n {vData}")
    
    # [2]: Check if user exist in DB
    vResponse = {}
    database.query(f"/User/{request["phone_number"]}", response=vResponse)
    print(f"[Debug] The response data is: {vResponse}")
    if vResponse["body"]:
        print(f"[Debug] User already exist in database: {vResponse["body"]}")
        raise HTTPException(status_code=400, detail="[Error]: User already exist in database")
    #TODO: Add to firebase, return real token and User ID
    return {"success": True, "token": "1234", "user": "defaultUser"}

@app.post("/api/auth/send-otp")
async def send_otp(request: Dict[Any, Any]):
    vData = deepcopy(request)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): raise HTTPException(status_code=400, detail=vError["description"])
    print(f"[Debug]: Converted data:\n {vData}")
    
    # [2]: Check if user exist in DB
    vResponse = {}
    database.query(f"/User/{request["phone_number"]}", response=vResponse)
    print(f"[Debug] The response data is: {vResponse}")
    if not vResponse["body"]:
        print("[Debug] User not found in database, sending OTP")
        #TODO: Implement send OTP
        # store {"OTP": "token"} in database /OTP
        # wait until receive register
        # delete otp, send message back
        return {"success": False}
    
    # [3]: Validate user data
    print("[Debug] User found in database, validating...")
    if not validate(vResponse["body"], "name",     str, str, vError, required=True): raise HTTPException(status_code=400, detail="[Error]: Database error")
    if not validate(vResponse["body"], "password", str, str, vError, required=True): raise HTTPException(status_code=400, detail="[Error]: Database error")
    print("[Debug] User data is valid")
    return {"success": True}
