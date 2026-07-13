import os
import string
import random
import time
import uuid
import logging
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename

# Configurar logging para debug
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'lucas_r_secret_key_123')
# Configuração do Socket.IO
socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    logger=True,
    engineio_logger=True,
    async_mode='threading'
)

# Armazenamento em memória (volátil)
salas = {}

# Configuração de upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mp3', 'ogg', 'wav', 'webm', 'pdf', 'doc', 'docx', 'txt'}
MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def tipo_midia(ext):
    if ext in {'png','jpg','jpeg','gif','webp'}:
        return 'imagem'
    elif ext in {'mp4','webm'}:
        return 'video'
    elif ext in {'mp3','ogg','wav'}:
        return 'audio'
    else:
        return 'arquivo'

def gerar_codigo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/entrar', methods=['POST'])
def entrar():
    email = request.form.get('email', '').strip()
    if not email or '@' not in email:
        return redirect(url_for('index'))
    session['email'] = email
    session['apelido'] = email.split('@')[0]
    logger.info(f"Usuário entrou: {email}")
    return redirect(url_for('salas_view'))

@app.route('/salas')
def salas_view():
    if 'email' not in session:
        return redirect(url_for('index'))
    return render_template('salas.html', email=session['email'])

@app.route('/criar_sala')
def criar_sala():
    if 'email' not in session:
        return redirect(url_for('index'))
    codigo = gerar_codigo()
    salas[codigo] = {'mensagens': []}
    session['sala'] = codigo
    logger.info(f"Sala criada: {codigo}")
    return redirect(url_for('chat', codigo=codigo))

@app.route('/entrar_sala', methods=['POST'])
def entrar_sala():
    if 'email' not in session:
        return redirect(url_for('index'))
    codigo = request.form.get('codigo', '').strip().upper()
    if not codigo:
        return redirect(url_for('salas_view'))
    if codigo not in salas:
        salas[codigo] = {'mensagens': []}
    session['sala'] = codigo
    logger.info(f"Usuário entrou na sala: {codigo}")
    return redirect(url_for('chat', codigo=codigo))

@app.route('/chat/<codigo>')
def chat(codigo):
    if 'email' not in session:
        return redirect(url_for('index'))
    if codigo not in salas:
        salas[codigo] = {'mensagens': []}
    session['sala'] = codigo
    return render_template('chat.html', codigo=codigo, email=session['email'])

# CORREÇÃO: Usar request.sid e passar dados via cliente para evitar problemas de session
@socketio.on('connect')
def handle_connect():
    logger.info(f"Cliente conectado: {request.sid}")

@socketio.on('entrar')
def handle_entrar(data):
    try:
        codigo = data.get('sala')
        apelido = data.get('apelido', 'Anônimo')
        
        if not codigo:
            logger.error("Código da sala não fornecido")
            return
            
        if codigo not in salas:
            salas[codigo] = {'mensagens': []}
            
        join_room(codigo)
        logger.info(f"{apelido} entrou na sala {codigo}")
        
        emit('mensagem', {
            'tipo': 'sistema',
            'texto': f'{apelido} entrou na sala 🟢'
        }, room=codigo)
        
        # Garantir que mensagens históricas tenham id
        for m in salas[codigo]['mensagens']:
            if 'id' not in m:
                m['id'] = f"{m.get('apelido','anon')}-{int(time.time()*1000)}-{random.randint(1000,9999)}"
        emit('historico', {'mensagens': salas[codigo]['mensagens']})
    except Exception as e:
        logger.error(f"Erro ao entrar na sala: {e}")

@socketio.on('mensagem')
def handle_mensagem(data):
    try:
        codigo = data.get('sala')
        apelido = data.get('apelido', 'Anônimo')
        texto = data.get('texto', '').strip()
        midia = data.get('midia')
        
        if not codigo or codigo not in salas:
            logger.error(f"Sala inválida: {codigo}")
            return
            
        if texto or midia:
            msg_id = data.get('id') or f"{apelido}-{int(time.time()*1000)}"
            msg = {'id': msg_id, 'tipo': 'usuario', 'apelido': apelido, 'texto': texto}
            if midia:
                msg['midia'] = midia
            salas[codigo]['mensagens'].append(msg)
            emit('mensagem', msg, room=codigo)
            logger.info(f"Mensagem em {codigo}: {apelido}" + (" (mídia)" if midia else ""))
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")

@socketio.on('apagar_mensagem')
def handle_apagar_mensagem(data):
    try:
        codigo = data.get('sala')
        msg_id = data.get('id')
        apelido = data.get('apelido', '')
        
        if not codigo or codigo not in salas:
            return
        
        salas[codigo]['mensagens'] = [m for m in salas[codigo]['mensagens'] if m.get('id') != msg_id]
        emit('mensagem_apagada', {'id': msg_id, 'apelido': apelido}, room=codigo)
        logger.info(f"Mensagem {msg_id} apagada em {codigo}")
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Cliente desconectado: {request.sid}")

@app.route('/sair')
def sair():
    session.clear()
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_midia():
    if 'email' not in session:
        return {'erro': 'Não autenticado'}, 401
    
    if 'file' not in request.files:
        return {'erro': 'Nenhum arquivo enviado'}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {'erro': 'Nome de arquivo vazio'}, 400
    
    if not allowed_file(file.filename):
        return {'erro': 'Tipo de arquivo não permitido'}, 400
    
    ext = file.filename.rsplit('.', 1)[1].lower()
    nome_unico = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, nome_unico))
    
    return {
        'arquivo': nome_unico,
        'ext': ext,
        'tipo': tipo_midia(ext)
    }

@app.route('/uploads/<nome>')
def arquivo_upload(nome):
    return send_from_directory(UPLOAD_FOLDER, nome)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080)