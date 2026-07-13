import os
import sqlite3
import uuid
import time
import logging
import json
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, jsonify
from flask_socketio import SocketIO, emit, join_room

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'voicemail_secret_123')

# Upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mp3', 'ogg', 'wav', 'webm', 'pdf', 'doc', 'docx', 'txt'}
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PERFIL_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'perfil')
os.makedirs(PERFIL_FOLDER, exist_ok=True)

FUNDO_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'fundos')
os.makedirs(FUNDO_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def tipo_midia(ext):
    if ext in {'png','jpg','jpeg','gif','webp'}:
        return 'imagem'
    elif ext in {'mp4','webm'}:
        return 'video'
    elif ext in {'mp3','ogg','wav'}:
        return 'audio'
    return 'arquivo'

# ─── Banco SQLite ───────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), 'voicemail.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS usuarios (
            email TEXT PRIMARY KEY,
            apelido TEXT NOT NULL,
            foto_perfil TEXT DEFAULT NULL,
            papel_parede TEXT DEFAULT 'default',
            criado_em TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS contatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dono_email TEXT NOT NULL,
            contato_email TEXT NOT NULL,
            contato_apelido TEXT,
            adicionado_em TEXT DEFAULT (datetime('now')),
            UNIQUE(dono_email, contato_email),
            FOREIGN KEY(dono_email) REFERENCES usuarios(email),
            FOREIGN KEY(contato_email) REFERENCES usuarios(email)
        );
        CREATE TABLE IF NOT EXISTS conversas (
            id TEXT PRIMARY KEY,
            email1 TEXT NOT NULL,
            email2 TEXT NOT NULL,
            criada_em TEXT DEFAULT (datetime('now')),
            UNIQUE(email1, email2)
        );
        CREATE TABLE IF NOT EXISTS mensagens (
            id TEXT PRIMARY KEY,
            conversa_id TEXT NOT NULL,
            remetente TEXT NOT NULL,
            texto TEXT DEFAULT '',
            midia_json TEXT,
            criada_em TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(conversa_id) REFERENCES conversas(id)
        );
        CREATE INDEX IF NOT EXISTS idx_mensagens_conversa ON mensagens(conversa_id, criada_em);
    ''')
    # Migração: adicionar colunas se não existirem (para quem já tem o banco)
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN foto_perfil TEXT DEFAULT NULL")
    except:
        pass
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN papel_parede TEXT DEFAULT 'default'")
    except:
        pass
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN fundo_app TEXT DEFAULT 'default'")
    except:
        pass
    conn.commit()
    conn.close()

init_db()

@app.context_processor
def inject_user():
    if 'email' in session:
        conn = get_db()
        user = conn.execute("SELECT foto_perfil, papel_parede, fundo_app FROM usuarios WHERE email=?", (session['email'],)).fetchone()
        conn.close()
        if user:
            return {
                'minha_foto': user['foto_perfil'],
                'minha_papel': user['papel_parede'],
                'meu_fundo': user['fundo_app'] or 'default'
            }
    return {'minha_foto': None, 'minha_papel': 'default', 'meu_fundo': 'default'}

# Socket.IO
socketio = SocketIO(app, cors_allowed_origins="*",
                    ping_timeout=60, ping_interval=25,
                    logger=True, engineio_logger=True,
                    async_mode='threading')

# ─── Utilitários ────────────────────────────────────────────
def pegar_ou_criar_conversa(email1, email2):
    a, b = sorted([email1.lower(), email2.lower()])
    conn = get_db()
    row = conn.execute("SELECT id FROM conversas WHERE email1=? AND email2=?", (a, b)).fetchone()
    if row:
        conn.close()
        return row['id']
    conv_id = str(uuid.uuid4())
    conn.execute("INSERT INTO conversas (id, email1, email2) VALUES (?, ?, ?)", (conv_id, a, b))
    conn.commit()
    conn.close()
    return conv_id

def sala_id(conversa_id):
    return f"conv_{conversa_id}"

# ─── Rotas ──────────────────────────────────────────────────
@app.route('/')
def index():
    if 'email' in session:
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/entrar', methods=['POST'])
def entrar():
    email = request.form.get('email', '').strip().lower()
    apelido = request.form.get('apelido', '').strip()
    if not email or '@' not in email:
        return redirect(url_for('index'))
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    if user:
        session['email'] = email
        session['apelido'] = user['apelido']
    else:
        if not apelido:
            apelido = email.split('@')[0]
        conn.execute("INSERT INTO usuarios (email, apelido) VALUES (?, ?)", (email, apelido))
        conn.commit()
        session['email'] = email
        session['apelido'] = apelido
    conn.close()
    return redirect(url_for('home'))

@app.route('/gerar_anonimo', methods=['POST'])
def gerar_anonimo():
    apelido = request.form.get('apelido', '').strip()
    if not apelido:
        return redirect(url_for('index'))
    import uuid
    codigo = uuid.uuid4().hex[:8]
    email = f"{codigo}@anon.voicemail"
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    while user:
        codigo = uuid.uuid4().hex[:8]
        email = f"{codigo}@anon.voicemail"
        user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    conn.execute("INSERT INTO usuarios (email, apelido) VALUES (?, ?)", (email, apelido))
    conn.commit()
    conn.close()
    session['email'] = email
    session['apelido'] = apelido
    return redirect(url_for('home'))

@app.route('/home')
def home():
    if 'email' not in session:
        return redirect(url_for('index'))
    email = session['email']
    erro = request.args.get('erro', '')
    conn = get_db()
    # Buscar conversas do usuário
    rows = conn.execute("""
        SELECT c.id, c.email1, c.email2,
               (SELECT texto FROM mensagens WHERE conversa_id = c.id ORDER BY criada_em DESC LIMIT 1) as ultima_msg,
               (SELECT criada_em FROM mensagens WHERE conversa_id = c.id ORDER BY criada_em DESC LIMIT 1) as ultima_data
        FROM conversas c
        WHERE c.email1=? OR c.email2=?
        ORDER BY ultima_data DESC
    """, (email, email)).fetchall()
    conversas = []
    for r in rows:
        outro = r['email2'] if r['email1'] == email else r['email1']
        outro_user = conn.execute("SELECT apelido, foto_perfil FROM usuarios WHERE email=?", (outro,)).fetchone()
        conversas.append({
            'id': r['id'],
            'outro_email': outro,
            'outro_apelido': outro_user['apelido'] if outro_user else outro,
            'outro_foto': outro_user['foto_perfil'] if outro_user and outro_user['foto_perfil'] else None,
            'ultima_msg': r['ultima_msg'] or 'Nenhuma mensagem ainda',
            'ultima_data': r['ultima_data']
        })
    # Buscar contatos
    contatos = conn.execute("""
        SELECT c.contato_email, COALESCE(c.contato_apelido, u.apelido) as apelido, u.foto_perfil
        FROM contatos c
        LEFT JOIN usuarios u ON u.email = c.contato_email
        WHERE c.dono_email=?
        ORDER BY apelido
    """, (email,)).fetchall()
    # Pegar minha própria foto
    eu = conn.execute("SELECT foto_perfil FROM usuarios WHERE email=?", (email,)).fetchone()
    minha_foto = eu['foto_perfil'] if eu and eu['foto_perfil'] else None
    conn.close()
    return render_template('home.html', conversas=conversas, contatos=[dict(c) for c in contatos],
                           erro=erro, minha_foto=minha_foto)

@app.route('/adicionar_contato', methods=['POST'])
def adicionar_contato():
    if 'email' not in session:
        return redirect(url_for('index'))
    email_contato = request.form.get('email', '').strip().lower()
    if not email_contato or '@' not in email_contato:
        return redirect(url_for('home'))
    if email_contato == session['email']:
        return redirect(url_for('home'))
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email_contato,)).fetchone()
    if not user:
        conn.close()
        return redirect(url_for('home', erro='Pessoa não cadastrada no VoiceMail'))
    try:
        conn.execute("INSERT INTO contatos (dono_email, contato_email) VALUES (?, ?)",
                     (session['email'], email_contato))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect(url_for('home'))

# ─── Convite por Link ────────────────────────────────────────
@app.route('/convite/<email_convidante>')
def pagina_convite(email_convidante):
    email_convidante = email_convidante.lower()
    if 'email' in session and session['email'] == email_convidante:
        return redirect(url_for('home'))
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email_convidante,)).fetchone()
    conn.close()
    if not user:
        return render_template('convite.html', convite_valido=False,
                               convidante_email=email_convidante,
                               convidante_apelido=email_convidante.split('@')[0],
                               convidante_foto=None)
    # Se já tem sessão, pula pra home
    if 'email' in session:
        # Auto-adicionar contato
        conn2 = get_db()
        try:
            conn2.execute("INSERT INTO contatos (dono_email, contato_email) VALUES (?, ?)",
                         (session['email'], email_convidante))
        except:
            pass
        conn2.close()
        return redirect(url_for('chat_com', email_contato=email_convidante))
    return render_template('convite.html', convite_valido=True,
                           convidante_email=email_convidante,
                           convidante_apelido=user['apelido'],
                           convidante_foto=user['foto_perfil'])

@app.route('/entrar_com_convite/<email_convidante>', methods=['POST'])
def entrar_com_convite(email_convidante):
    email_convidante = email_convidante.lower()
    email = request.form.get('email', '').strip().lower()
    apelido = request.form.get('apelido', '').strip()
    if not email or '@' not in email:
        return redirect(url_for('pagina_convite', email_convidante=email_convidante))
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    if user:
        session['email'] = email
        session['apelido'] = user['apelido']
    else:
        if not apelido:
            apelido = email.split('@')[0]
        conn.execute("INSERT INTO usuarios (email, apelido) VALUES (?, ?)", (email, apelido))
        conn.commit()
        session['email'] = email
        session['apelido'] = apelido
    # Auto-adicionar o convidante aos contatos
    try:
        conn.execute("INSERT INTO contatos (dono_email, contato_email, contato_apelido) VALUES (?, ?, ?)",
                     (email, email_convidante, None))
    except:
        pass
    conn.close()
    return redirect(url_for('chat_com', email_contato=email_convidante))

@app.route('/remover_contato', methods=['POST'])
def remover_contato():
    if 'email' not in session:
        return redirect(url_for('index'))
    email_contato = request.form.get('email', '')
    conn = get_db()
    conn.execute("DELETE FROM contatos WHERE dono_email=? AND contato_email=?", (session['email'], email_contato))
    conn.commit()
    conn.close()
    return redirect(url_for('home'))

@app.route('/chat/<email_contato>')
def chat_com(email_contato):
    if 'email' not in session:
        return redirect(url_for('index'))
    email_contato = email_contato.lower()
    if email_contato == session['email']:
        return redirect(url_for('home'))
    conn = get_db()
    outro = conn.execute("SELECT * FROM usuarios WHERE email=?", (email_contato,)).fetchone()
    if not outro:
        conn.close()
        return redirect(url_for('home'))
    # Meu papel de parede
    eu = conn.execute("SELECT papel_parede, foto_perfil FROM usuarios WHERE email=?", (session['email'],)).fetchone()
    papel_parede = eu['papel_parede'] if eu and eu['papel_parede'] else 'default'
    minha_foto = eu['foto_perfil'] if eu and eu['foto_perfil'] else None
    conv_id = pegar_ou_criar_conversa(session['email'], email_contato)
    msgs = conn.execute("""
        SELECT id, remetente, texto, midia_json, criada_em
        FROM mensagens WHERE conversa_id=?
        ORDER BY criada_em ASC LIMIT 200
    """, (conv_id,)).fetchall()
    conn.close()
    historico = []
    for m in msgs:
        msg = {'id': m['id'], 'remetente': m['remetente'], 'texto': m['texto'], 'data': m['criada_em']}
        if m['midia_json']:
            msg['midia'] = json.loads(m['midia_json'])
        historico.append(msg)
    return render_template('chat_direto.html', email_contato=email_contato,
                           email_logado=session['email'],
                           outro_apelido=outro['apelido'],
                           outro_foto=outro['foto_perfil'] if outro['foto_perfil'] else None,
                           minha_foto=minha_foto,
                           historico=historico, conv_id=conv_id,
                           papel_parede=papel_parede)

@app.route('/sair')
def sair():
    session.clear()
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_midia():
    if 'email' not in session:
        return {'erro': 'Não autenticado'}, 401
    if 'file' not in request.files:
        return {'erro': 'Nenhum arquivo'}, 400
    file = request.files['file']
    if not file.filename or not allowed_file(file.filename):
        return {'erro': 'Tipo não permitido'}, 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    nome = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, nome))
    return {'arquivo': nome, 'ext': ext, 'tipo': tipo_midia(ext)}

@app.route('/uploads/<nome>')
def arquivo_upload(nome):
    return send_from_directory(UPLOAD_FOLDER, nome)

@app.route('/perfil/<nome>')
def arquivo_perfil(nome):
    return send_from_directory(PERFIL_FOLDER, nome)

@app.route('/fundos/<nome>')
def arquivo_fundo(nome):
    return send_from_directory(FUNDO_FOLDER, nome)

@app.route('/apagar_mensagem', methods=['POST'])
def apagar_mensagem():
    if 'email' not in session:
        return {'ok': False, 'erro': 'Não autenticado'}, 401
    data = request.get_json()
    msg_id = data.get('msg_id', '')
    conv_id = data.get('conv_id', '')
    email = data.get('email', '')
    if not msg_id:
        return {'ok': False}, 400
    conn = get_db()
    msg = conn.execute("SELECT remetente FROM mensagens WHERE id=? AND conversa_id=?", (msg_id, conv_id)).fetchone()
    if msg and msg['remetente'] == email:
        conn.execute("DELETE FROM mensagens WHERE id=?", (msg_id,))
        conn.commit()
    conn.close()
    return {'ok': True}

# ─── Configurações ──────────────────────────────────────────
@app.route('/config')
def config():
    if 'email' not in session:
        return redirect(url_for('index'))
    conn = get_db()
    eu = conn.execute("SELECT * FROM usuarios WHERE email=?", (session['email'],)).fetchone()
    conn.close()
    return render_template('config.html', usuario=eu)

@app.route('/salvar_apelido', methods=['POST'])
def salvar_apelido():
    if 'email' not in session:
        return {'ok': False}, 401
    novo_apelido = request.form.get('apelido', '').strip()
    if novo_apelido:
        conn = get_db()
        conn.execute("UPDATE usuarios SET apelido=? WHERE email=?", (novo_apelido, session['email']))
        conn.commit()
        conn.close()
        session['apelido'] = novo_apelido
    return redirect(url_for('config'))

@app.route('/upload_foto_perfil', methods=['POST'])
def upload_foto_perfil():
    if 'email' not in session:
        return {'ok': False}, 401
    if 'foto' not in request.files:
        return redirect(url_for('config'))
    file = request.files['foto']
    if not file.filename:
        return redirect(url_for('config'))
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    if ext not in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
        return redirect(url_for('config'))
    nome = f"perfil_{session['email'].replace('@','_').replace('.','_')}.{ext}"
    file.save(os.path.join(PERFIL_FOLDER, nome))
    conn = get_db()
    conn.execute("UPDATE usuarios SET foto_perfil=? WHERE email=?", (nome, session['email']))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))

@app.route('/remover_foto_perfil', methods=['POST'])
def remover_foto_perfil():
    if 'email' not in session:
        return redirect(url_for('index'))
    conn = get_db()
    eu = conn.execute("SELECT foto_perfil FROM usuarios WHERE email=?", (session['email'],)).fetchone()
    if eu and eu['foto_perfil']:
        caminho = os.path.join(PERFIL_FOLDER, eu['foto_perfil'])
        if os.path.exists(caminho):
            os.remove(caminho)
    conn.execute("UPDATE usuarios SET foto_perfil=NULL WHERE email=?", (session['email'],))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))

@app.route('/escolher_papel', methods=['POST'])
def escolher_papel():
    if 'email' not in session:
        return redirect(url_for('index'))
    papel = request.form.get('papel', 'default')
    conn = get_db()
    conn.execute("UPDATE usuarios SET papel_parede=? WHERE email=?", (papel, session['email']))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))

@app.route('/upload_fundo_app', methods=['POST'])
def upload_fundo_app():
    if 'email' not in session:
        return redirect(url_for('index'))
    if 'fundo' not in request.files:
        return redirect(url_for('config'))
    file = request.files['fundo']
    if not file.filename:
        return redirect(url_for('config'))
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    if ext not in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
        return redirect(url_for('config'))
    nome = f"fundo_{session['email'].replace('@','_').replace('.','_')}.{ext}"
    file.save(os.path.join(FUNDO_FOLDER, nome))
    conn = get_db()
    conn.execute("UPDATE usuarios SET fundo_app=? WHERE email=?", (nome, session['email']))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))

@app.route('/remover_fundo_app', methods=['POST'])
def remover_fundo_app():
    if 'email' not in session:
        return redirect(url_for('index'))
    conn = get_db()
    user = conn.execute("SELECT fundo_app FROM usuarios WHERE email=?", (session['email'],)).fetchone()
    if user and user['fundo_app']:
        caminho = os.path.join(FUNDO_FOLDER, user['fundo_app'])
        if os.path.exists(caminho):
            os.remove(caminho)
    conn.execute("UPDATE usuarios SET fundo_app='default' WHERE email=?", (session['email'],))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))

# ─── Socket.IO ──────────────────────────────────────────────
@socketio.on('connect')
def handle_connect():
    logger.info(f"Cliente conectado: {request.sid}")

@socketio.on('entrar_chat')
def handle_entrar_chat(data):
    conv_id = data.get('conv_id')
    if conv_id:
        join_room(sala_id(conv_id))
        logger.info(f"Cliente entrou na conversa {conv_id}")

@socketio.on('registrar_usuario')
def handle_registrar(data):
    email = data.get('email', '')
    if email:
        room = f"user_{email.replace('@','_').replace('.','_')}"
        join_room(room)
        logger.info(f"Usuario registrado: {email} -> {room}")

@socketio.on('mensagem_privada')
def handle_mensagem(data):
    try:
        conv_id = data.get('conv_id')
        remetente = data.get('remetente', '')
        texto = data.get('texto', '').strip()
        midia = data.get('midia')
        sticker = data.get('sticker')
        if not conv_id or not remetente:
            return
        if not texto and not midia and not sticker:
            return
        msg_id = f"{remetente}-{int(time.time()*1000)}"
        conn = get_db()
        midia_json = None
        if midia:
            midia_json = json.dumps(midia)
        if sticker:
            # Salva sticker como midia do tipo imagem
            sticker_data = {'tipo': 'imagem', 'arquivo': sticker.replace('/static/stickers/', '')}
            midia_json = json.dumps(sticker_data)
        conn.execute(
            "INSERT INTO mensagens (id, conversa_id, remetente, texto, midia_json) VALUES (?, ?, ?, ?, ?)",
            (msg_id, conv_id, remetente, texto if texto else None, midia_json)
        )
        conn.commit()
        conn.close()
        msg = {'id': msg_id, 'remetente': remetente, 'texto': texto, 'conv_id': conv_id, 'apelido': data.get('apelido', '')}
        if midia:
            msg['midia'] = midia
        if sticker:
            msg['sticker'] = sticker
        # Envia pro chat
        emit('nova_mensagem', msg, room=sala_id(conv_id))
        # Envia notificação pro outro participante (se estiver na home)
        destino = data.get('destino', '')
        if destino:
            user_room = f"user_{destino.replace('@','_').replace('.','_')}"
            emit('notificacao_mensagem', msg, room=user_room)
    except Exception as e:
        logger.error(f"Erro mensagem: {e}")

@socketio.on('apagar_mensagem')
def handle_apagar(data):
    try:
        msg_id = data.get('msg_id', '')
        conv_id = data.get('conv_id', '')
        email = data.get('email', '')
        if not msg_id or not conv_id or not email:
            return
        conn = get_db()
        msg = conn.execute("SELECT remetente FROM mensagens WHERE id=? AND conversa_id=?", (msg_id, conv_id)).fetchone()
        if msg and msg['remetente'] == email:
            conn.execute("DELETE FROM mensagens WHERE id=?", (msg_id,))
            conn.commit()
        conn.close()
        emit('msg_apagada', {'id': msg_id, 'remetente': email}, room=sala_id(conv_id))
    except Exception as e:
        logger.error(f"Erro apagar: {e}")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080)