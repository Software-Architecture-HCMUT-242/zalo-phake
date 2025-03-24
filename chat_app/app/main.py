from flask import Flask, request, jsonify
from flask_cors import CORS
from firebase import FirebaseDB
from copy import deepcopy

database = FirebaseDB()
database.connect()
app = Flask(__name__)
CORS(app, supports_credentials=True)

@app.route("/", methods=["GET"])
def ping():
    return jsonify({"pong": True}), 200

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


@app.route("/api/auth/login", methods=["POST"])
def login():
    vRequest = deepcopy(request.json)
    vData = deepcopy(request.json)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vData, "password",     str, str, vError, required=True): return jsonify({"error": vError["description"]}), 400
    print(f"[Debug]: Converted data:\n {vData}")
    
    #TODO: Query firebase, return real token and User ID
    return jsonify({"token": "1234", "user": "defaultUser", "success": True}), 200

@app.route("/api/auth/register", methods=["POST"])
def register():
    vRequest = deepcopy(request.json)
    vData = deepcopy(request.json)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vData, "name",         str, str, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vData, "password",     str, str, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vData, "otp",          str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    print(f"[Debug]: Converted data:\n {vData}")
    
    # [2]: Check if user exist in DB
    vResponse = {}
    database.query(f"/User/{vRequest["phone_number"]}", response=vResponse)
    print(f"[Debug] The response data is: {vResponse}")
    if vResponse["body"]:
        # [2.1]: Validate user data
        print("[Debug] User found in database, validating...")
        if not validate(vResponse["body"], "name",         str, str, vError, required=True): return jsonify({"error": "[Error]: Databse error"}), 400
        if not validate(vResponse["body"], "password",     str, str, vError, required=True): return jsonify({"error": "[Error]: Databse error"}), 400
        print(f"[Debug] User already exist in database: {vResponse["body"]}")
        return jsonify({"error": "[Error]: User already exist"}), 400
    #TODO: Add to firebase, return real token and User ID
    return jsonify({"token": "1234", "user": "defaultUser", "success": True}), 200

@app.route("/api/auth/send-otp", methods=["POST"])
def send_otp():
    vRequest = deepcopy(request.json)
    vData = deepcopy(request.json)
    vError = {}
    # [1]: Validate request body
    if not validate(vData, "phone_number", str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    print(f"[Debug]: Converted data:\n {vData}")
    
    # [2]: Check if user exist in DB
    vResponse = {}
    database.query(f"/User/{vRequest["phone_number"]}", response=vResponse)
    print(f"[Debug] The response data is: {vResponse}")
    if not vResponse["body"]:
        print("[Debug] User not found in database, sending OTP")
        #TODO: Implement send OTP
        # store {"OTP": "token"} in database /OTP
        # wait until receive register
        # delete otp, send message back
        return jsonify({"success": False}), 200
    
    # [3]: Validate user data
    print("[Debug] User found in database, validating...")
    if not validate(vResponse["body"], "name",         str, str, vError, required=True): return jsonify({"error": "[Error]: Databse error"}), 400
    if not validate(vResponse["body"], "password",     str, str, vError, required=True): return jsonify({"error": "[Error]: Databse error"}), 400
    print("[Debug] User data is valid")
    return jsonify({"success": True}), 200

if __name__ == "__main__":
    # db = FirebaseDB()
    # db.connect()
    # res = {}
    # db.query("/User", response=res)
    # print(res)
    # db.query("/User/0908765432/name", response=res)
    # db.insert("/User/0900000000", 123)
    # print(res)

    app.run(debug=True)
