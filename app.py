import os
import uuid
import string
import random
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*")

# Salas na memória (some tudo se reiniciar o servidor)
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
    return redirect(url_for('salas'))

@app.route('/salas')
def salas():
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
    return redirect(url_for('chat', codigo=codigo))

@app.route('/entrar_sala', methods=['POST'])
def entrar_sala():
    if 'email' not in session:
        return redirect(url_for('index'))
    codigo = request.form.get('codigo', '').strip().upper()
    if codigo in salas:
        session['sala'] = codigo
        return redirect(url_for('chat', codigo=codigo))
    else:
        return redirect(url_for('salas', erro='Sala não encontrada!'))

@app.route('/chat/<codigo>')
def chat(codigo):
    if 'email' not in session:
        return redirect(url_for('index'))
    if codigo not in salas:
        return redirect(url_for('salas'))
    session['sala'] = codigo
    return render_template('chat.html', codigo=codigo, email=session['email'])

@socketio.on('entrar')
def handle_entrar(data):
    codigo = data.get('sala')
    if codigo in salas:
        join_room(codigo)
        apelido = session.get('apelido', 'Anônimo')
        emit('mensagem', {
            'tipo': 'sistema',
            'texto': f'{apelido} entrou na sala 🟢'
        }, room=codigo)
        emit('historico', {'mensagens': salas[codigo]['mensagens']})

@socketio.on('mensagem')
def handle_mensagem(data):
    codigo = session.get('sala')
    if codigo in salas:
        apelido = session.get('apelido', 'Anônimo')
        texto = data.get('texto', '').strip()
        if texto:
            msg = {'tipo': 'usuario', 'apelido': apelido, 'texto': texto}
            salas[codigo]['mensagens'].append(msg)
            emit('mensagem', msg, room=codigo)

@app.route('/sair')
def sair():
    codigo = session.get('sala')
    if codigo and codigo in salas:
        apelido = session.get('apelido', 'Anônimo')
        socketio.emit('mensagem', {
            'tipo': 'sistema',
            'texto': f'{apelido} saiu da sala 🔴'
        }, room=codigo)
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)