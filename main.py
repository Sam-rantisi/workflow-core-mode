from flask import Flask, request
from generator import generate_version
app = Flask(__name__)

@app.route('/generate', methods=['POST'])
def generate():
    version = request.args.get('version')
    output = generate_version(version)
    return {"status": "done", "output_path": output}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
