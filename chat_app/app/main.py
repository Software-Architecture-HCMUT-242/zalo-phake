from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/", methods=["GET"])
def ping():
    return jsonify({"pong": True}), 200

def validate(body, key, type_origin, type_convert, error, required=False):
    # [1]: Check if body has key
    if (key not in body) and required:
        error["description"] = f"[Error] Can't find key {key}"
        print(error)
        return False

    # [2]: Check type of request value
    if not isinstance(body[key], type_origin):
        error["description"] = f"[Error] Key {key} is not of type {type_origin}"
        print(error)
        return False
    
    # [3]: Try conversion to target type (to check number string like phone number, otp)
    try:
        body[key] = type_convert(body[key])
    except ValueError:
        error["description"] = f"[Error] Cannot convert {key} to {type_convert}"
        print(error)
        return False
    return True


@app.route("/api/auth/login", methods=["POST"])
def login():
    vRequest = request.json
    vError = {}
    if not validate(vRequest, "phone_number", str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vRequest, "password",     str, str, vError, required=True): return jsonify({"error": vError["description"]}), 400
    
    print(f"[Debug]: Converted request:\n {vRequest}")
    #TODO: Query firebase, return real token and User ID
    return jsonify({"token": "1234", "user": "defaultUser", "success": True}), 200

@app.route("/api/auth/register", methods=["POST"])
def register():
    vRequest = request.json
    vError = {}
    if not validate(vRequest, "phone_number", str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vRequest, "name",         str, str, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vRequest, "password",     str, str, vError, required=True): return jsonify({"error": vError["description"]}), 400
    if not validate(vRequest, "otp",          str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    
    print(f"[Debug]: Converted request:\n {vRequest}")
    #TODO: Add to firebase, return real token and User ID
    return jsonify({"token": "1234", "user": "defaultUser", "success": True}), 200

@app.route("/api/auth/send-otp", methods=["POST"])
def send_otp():
    vRequest = request.json
    vError = {}
    if not validate(vRequest, "phone_number", str, int, vError, required=True): return jsonify({"error": vError["description"]}), 400
    
    print(f"[Debug]: Converted request:\n {vRequest}")
    #TODO: Implement send OTP
    return jsonify({"success": True}), 200

if __name__ == "__main__":
    app.run(debug=True)
