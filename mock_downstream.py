import random

from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/process', methods=['POST'])
def process_transaction():
    data = request.get_json()
    transaction_id = data.get('transaction_id')
    
    # Simulate 80% success, 20% failure
    if random.random() < 0.8:
        return jsonify({
            'status': 'success',
            'transaction_id': transaction_id
        }), 200
    else:
        return jsonify({
            'status': 'error',
            'message': 'Downstream service temporarily unavailable'
        }), 503  # Service Unavailable

@app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001, debug=True)