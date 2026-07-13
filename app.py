import os
import string
import random
import logging
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room

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
    async_mode='eventlet'
)

# Armazenamento em memória (volátil)
salas = {}

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
        
        emit('historico', {'mensagens': salas[codigo]['mensagens']})
    except Exception as e:
        logger.error(f"Erro ao entrar na sala: {e}")

@socketio.on('mensagem')
def handle_mensagem(data):
    try:
        codigo = data.get('sala')
        apelido = data.get('apelido', 'Anônimo')
        texto = data.get('texto', '').strip()
        
        if not codigo or codigo not in salas:
            logger.error(f"Sala inválida: {codigo}")
            return
            
        if texto:
            msg = {'tipo': 'usuario', 'apelido': apelido, 'texto': texto}
            salas[codigo]['mensagens'].append(msg)
            emit('mensagem', msg, room=codigo)
            logger.info(f"Mensagem em {codigo}: {apelido}")
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Cliente desconectado: {request.sid}")

@app.route('/sair')
def sair():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080)