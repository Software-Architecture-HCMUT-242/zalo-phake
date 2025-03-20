from flask import request, jsonify, Flask
from datetime import datetime, timezone
from functools import wraps
import jwt
from flask_cors import CORS

app = Flask(__name__)
CORS(app, supports_credentials=True)

PREFIX = '/api/v1'


@app.route("/", methods=["GET"])
def ping():
    return jsonify({"pong": True}), 200


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or not token.startswith('Bearer '):
            return jsonify({'message': 'Token is missing or invalid'}), 401
        
        try:
            token = token.split(' ')[1]
            # You'll need to set up your secret key and implement proper JWT validation
            jwt.decode(token, 'your-secret-key', algorithms=['HS256'])
        except:
            return jsonify({'message': 'Token is invalid'}), 401
        
        return f(*args, **kwargs)
    return decorated

@app.route(f'{PREFIX}/chats', methods=['GET'])
@token_required
def get_chats():
    # Implementation would fetch chats from your database
    chats = []  # Replace with actual database query
    return jsonify({'chats': chats})

@app.route(f'{PREFIX}/chats', methods=['POST'])
@token_required
def create_chat():
    data = request.get_json()
    participant = data.get('participant')
    
    if not participant:
        return jsonify({'message': 'Participant is required'}), 400
        
    # Implementation would create chat in your database
    chat = {}  # Replace with actual chat creation
    return jsonify({'chat': chat}), 201

@app.route(f'{PREFIX}/chats/messages', methods=['GET'])
@token_required
def get_messages():
    limit = request.args.get('limit', type=int)
    before = request.args.get('before')  # timestamp
    
    # Implementation would fetch messages from your database
    messages = []  # Replace with actual database query
    return jsonify({'messages': messages})

@app.route(f'{PREFIX}/chats/messages', methods=['POST'])
@token_required
def send_message():
    data = request.get_json()
    content = data.get('content')
    
    if not content:
        return jsonify({'message': 'Content is required'}), 400
        
    # Implementation would save message to your database
    message = {
        'content': content,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        # Add other message properties
    }
    return jsonify({'message': message}), 201



if __name__ == '__main__':
    app.run(debug=True)