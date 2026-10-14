import asyncio
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr
from typing import Literal
from html.parser import HTMLParser
from telethon.extensions.html import parse as parse_telegram_html
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, Column, Integer, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from telethon import TelegramClient, errors
from telethon.tl.types import User
from .audit import parse_ids, compare


class Settings(BaseSettings):
    database_url: str
    telegram_api_id: int
    telegram_api_hash: SecretStr
    app_token: SecretStr
    session_dir: str = 'private'
    frontend_origin: str = 'http://localhost:3000'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
if len(settings.app_token.get_secret_value()) < 24:
    raise RuntimeError('APP_TOKEN deve ter pelo menos 24 caracteres')
engine = create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
Session = sessionmaker(bind=engine)
Base = declarative_base()


class Audit(Base):
    __tablename__ = 'audits'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    result = Column(JSON, nullable=False)


session_path = Path(settings.session_dir).resolve()
session_path.mkdir(parents=True, exist_ok=True)
if os.name != 'nt':
    session_path.chmod(0o700)
client = TelegramClient(str(session_path / 'account'), settings.telegram_api_id, settings.telegram_api_hash.get_secret_value(), flood_sleep_threshold=0, request_retries=0, connection_retries=1, raise_last_call_error=True)
lock = asyncio.Lock()
login = {}
progress = {'state': 'idle', 'processed': 0}


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    await client.connect()
    if os.name != 'nt':
        for file in session_path.glob('*.session*'):
            file.chmod(0o600)
    yield
    await client.disconnect()
    engine.dispose()


app = FastAPI(title='Telegram CRM — Contatos e auditoria', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])


async def telegram_authorized():
    # Consulta a própria conta para não depender de um estado de autorização em cache.
    return await client.get_me() is not None


async def authorize(authorization: str = Header(default='')):
    import secrets
    if not secrets.compare_digest(authorization, 'Bearer ' + settings.app_token.get_secret_value()):
        raise HTTPException(401, 'Token de acesso inválido')


class Phone(BaseModel):
    phone: str


class Code(BaseModel):
    code: str


class Password(BaseModel):
    password: SecretStr


@app.exception_handler(errors.RPCError)
async def telegram_error(request, exc):
    from fastapi.responses import JSONResponse
    if isinstance(exc, errors.FloodWaitError):
        return JSONResponse(status_code=429, content={'detail': 'Limite do Telegram. Aguarde antes de tentar novamente.', 'retry_after': exc.seconds}, headers={'Retry-After': str(exc.seconds)})
    if isinstance(exc, (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError, errors.PasswordHashInvalidError, errors.PhoneNumberInvalidError)):
        return JSONResponse(status_code=400, content={'detail': 'Telefone, código ou senha inválido/expirado. Reinicie o login se necessário.'})
    return JSONResponse(status_code=401, content={'detail': 'Falha de autenticação ou sessão Telegram. Conecte sua conta novamente.'})


@app.exception_handler(ConnectionError)
@app.exception_handler(OSError)
@app.exception_handler(asyncio.TimeoutError)
async def connection_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={'detail': 'Conexão indisponível. Verifique a rede e reinicie o backend se necessário.'})


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={'detail': 'Banco indisponível. Se tentou enviar, confira a conversa no Telegram antes de repetir.'})


@app.get('/health')
def health():
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    return {'status': 'ok'}


@app.get('/auth/status', dependencies=[Depends(authorize)])
async def auth_status():
    return {'authorized': await telegram_authorized()}


@app.post('/auth/phone', dependencies=[Depends(authorize)])
async def phone(body: Phone):
    async with lock:
        if await telegram_authorized():
            return {'state': 'authorized'}
        sent = await client.send_code_request(body.phone)
        login.clear()
        login.update(phone=body.phone, phone_code_hash=sent.phone_code_hash)
        return {'state': 'code_required'}


@app.post('/auth/code', dependencies=[Depends(authorize)])
async def code(body: Code):
    async with lock:
        if not login:
            raise HTTPException(400, 'Solicite um código primeiro')
        try:
            await client.sign_in(phone=login['phone'], phone_code_hash=login['phone_code_hash'], code=body.code)
        except errors.SessionPasswordNeededError:
            login['password_required'] = True
            return {'state': 'password_required'}
        login.clear()
        return {'state': 'authorized'}


@app.post('/auth/password', dependencies=[Depends(authorize)])
async def password(body: Password):
    async with lock:
        if not login.get('password_required'):
            raise HTTPException(400, 'Valide o código antes da senha 2FA')
        await client.sign_in(password=body.password.get_secret_value())
        login.clear()
        return {'state': 'authorized'}


@app.get('/audit/progress', dependencies=[Depends(authorize)])
def audit_progress():
    return progress


@app.post('/audit', dependencies=[Depends(authorize)])
async def audit(file: UploadFile = File(...), column: str | None = Form(default=None)):
    if lock.locked():
        raise HTTPException(409, 'Outra operação está em andamento')
    async with lock:
        if not await telegram_authorized():
            raise HTTPException(401, 'Conecte sua conta Telegram')
        data = await file.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, 'Planilha acima de 10 MB')
        try:
            ids, info = await asyncio.to_thread(parse_ids, data, column)
        except Exception:
            raise HTTPException(400, 'Planilha inválida ou coluna ambígua. Informe o nome exato da coluna de IDs.')
        if not ids:
            raise HTTPException(400, 'Nenhum ID válido encontrado')
        dialogs = {}
        progress.update(state='reading', processed=0)
        try:
            async for dialog in client.iter_dialogs():
                progress['processed'] += 1
                entity = dialog.entity
                if isinstance(entity, User) and not entity.bot and not entity.is_self:
                    dialogs[entity.id] = {'name': ' '.join(filter(None, [entity.first_name, entity.last_name])), 'username': entity.username, 'last_interaction': dialog.date.isoformat() if dialog.date else None}
            result = compare(ids, dialogs)
            result['import'] = info
            with Session() as db:
                item = Audit(result=result)
                db.add(item)
                db.commit()
                result['audit_id'] = item.id
            progress.update(state='complete')
            return result
        except Exception:
            progress.update(state='error')
            raise


@app.get('/audit/latest', dependencies=[Depends(authorize)])
def latest():
    with Session() as db:
        item = db.query(Audit).order_by(Audit.id.desc()).first()
        if not item:
            return None
        return {**item.result, 'audit_id': item.id}


@app.get('/audit/{audit_id}/export', dependencies=[Depends(authorize)])
def export(audit_id: int, format: str = 'xlsx'):
    if format not in {'csv', 'xlsx'}:
        raise HTTPException(400, 'Formato inválido')
    with Session() as db:
        item = db.get(Audit, audit_id)
        if not item:
            raise HTTPException(404, 'Auditoria inexistente')
        frame = pd.DataFrame(item.result['rows'])
    # Evita execução de fórmulas ao abrir relatórios em planilhas.
    for col in frame.columns:
        frame[col] = frame[col].map(lambda v: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v)
    output = io.BytesIO()
    if format == 'xlsx':
        frame.to_excel(output, index=False, engine='openpyxl')
        media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        output.write(frame.to_csv(index=False).encode('utf-8-sig'))
        media = 'text/csv'
    output.seek(0)
    return StreamingResponse(output, media_type=media, headers={'Content-Disposition': f'attachment; filename="auditoria-{audit_id}.{format}"'})

# O módulo de contatos é separado da auditoria; só envia mediante ação individual.
from sqlalchemy import String, Boolean
from .leads import parse_leads
import uuid


class Lead(Base):
    __tablename__ = 'leads'
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, nullable=False)
    name = Column(String(200), default='')
    telegram_id = Column(String(32), nullable=True)
    status = Column(String(20), default='pending')
    last_contact = Column(DateTime(timezone=True), nullable=True)
    blocked = Column(Boolean, default=False)


class SendAttempt(Base):
    __tablename__ = 'send_attempts'
    id = Column(String(36), primary_key=True)
    lead_id = Column(Integer, nullable=False)
    state = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SendControl(Base):
    __tablename__ = 'send_control'
    id = Column(Integer, primary_key=True)
    next_allowed = Column(DateTime(timezone=True), nullable=True)


def lead_dict(item):
    return {'id': item.id, 'name': item.name, 'username': item.username, 'telegram_id': item.telegram_id, 'status': item.status, 'last_contact': item.last_contact.isoformat() if item.last_contact else None, 'blocked': item.blocked}


@app.get('/leads', dependencies=[Depends(authorize)])
def list_leads():
    with Session() as db:
        return [lead_dict(x) for x in db.query(Lead).filter(Lead.status != 'deleted').order_by(Lead.id).all()]


@app.post('/leads/import', dependencies=[Depends(authorize)])
async def import_leads(file: UploadFile = File(...)):
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, 'Arquivo acima de 10 MB')
    try:
        rows, info = await asyncio.to_thread(parse_leads, data, file.filename or '')
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(400, 'Arquivo inválido. Use XLSX/CSV com Nome e @usuario.')
    if not rows:
        raise HTTPException(400, 'Nenhum username válido encontrado')
    async with lock:
        with Session() as db:
            existing_rows = db.query(Lead).all()
            existing = {x.username for x in existing_rows}
            excluded_names = {x.username for x in existing_rows if x.status == 'deleted'}
            excluded_ids = {x.telegram_id for x in existing_rows if x.status == 'deleted' and x.telegram_id}
            added, excluded = 0, 0
            for row in rows:
                if row['username'] in excluded_names or (row['telegram_id'] and row['telegram_id'] in excluded_ids):
                    excluded += 1
                    continue
                if row['username'] not in existing:
                    db.add(Lead(**row))
                    existing.add(row['username'])
                    added += 1
            db.commit()
    return {**info, 'added': added, 'already_imported': len(rows)-added-excluded, 'excluded': excluded}


class BlockLead(BaseModel):
    blocked: bool


@app.post('/leads/{lead_id}/block', dependencies=[Depends(authorize)])
def block_lead(lead_id: int, body: BlockLead):
    with Session() as db:
        item = db.get(Lead, lead_id)
        if item is None or item.status == 'deleted':
            raise HTTPException(404, 'Contato não encontrado')
        item.blocked = body.blocked
        db.commit()
        return lead_dict(item)



class DeleteLead(BaseModel):
    confirmed: bool = False


@app.post('/leads/{lead_id}/delete', dependencies=[Depends(authorize)])
async def delete_lead(lead_id: int, body: DeleteLead):
    if not body.confirmed:
        raise HTTPException(400, 'Confirme a exclusão do contato')
    if lock.locked():
        raise HTTPException(409, 'Outra operação está em andamento. Aguarde antes de excluir.')
    async with lock:
        with Session() as db:
            item = db.get(Lead, lead_id)
            if item is None:
                raise HTTPException(404, 'Contato não encontrado')
            if item.status == 'deleted':
                return {'state': 'deleted', 'lead_id': lead_id, 'removed': 0}
            # Mantemos a exclusão e tentativas históricas para impedir reimportação/reenvio.
            related = db.query(Lead).filter(Lead.telegram_id == item.telegram_id).all() if item.telegram_id else [item]
            removed = 0
            for contact in related:
                if contact.status != 'deleted':
                    contact.status = 'deleted'
                    contact.blocked = True
                    removed += 1
            db.commit()
            return {'state': 'deleted', 'lead_id': lead_id, 'removed': removed}


def set_cooldown(db, seconds):
    from datetime import timedelta
    control = db.get(SendControl, 1)
    if control is None:
        control = SendControl(id=1)
        db.add(control)
    control.next_allowed = datetime.now(timezone.utc) + timedelta(seconds=seconds)


class MessageMarkup(HTMLParser):
    allowed = {'b', 'strong', 'i', 'em', 'u', 's', 'del', 'code', 'pre'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.allowed or attrs or len(self.stack) >= 32:
            raise ValueError('Use apenas b, i, u, s, code ou pre, sem atributos.')
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError('Confira a abertura e o fechamento das marcações HTML.')

    def handle_startendtag(self, tag, attrs):
        raise ValueError('Marcações devem conter abertura e fechamento.')

    def handle_comment(self, data):
        raise ValueError('Comentários HTML não são suportados.')

    def handle_decl(self, decl):
        raise ValueError('Declarações HTML não são suportadas.')

    def unknown_decl(self, data):
        raise ValueError('Declarações HTML não são suportadas.')

    def handle_pi(self, data):
        raise ValueError('Instruções HTML não são suportadas.')


def message_text(text, formatting):
    if len(text) > 32768:
        raise ValueError('Mensagem muito grande.')
    if formatting == 'plain':
        return text
    validator = MessageMarkup()
    validator.feed(text)
    validator.close()
    if validator.stack:
        raise ValueError('Feche todas as marcações HTML antes de enviar.')
    rendered, _ = parse_telegram_html(text)
    return rendered


@app.post('/leads/{lead_id}/send', dependencies=[Depends(authorize)])
async def send_one(lead_id: int, text: str = Form(default=''), confirmed: bool = Form(default=False), request_id: str = Form(...), image: UploadFile | None = File(default=None), formatting: Literal['plain', 'html'] = Form(default='plain')):
    try:
        request_id = str(uuid.UUID(request_id))
    except ValueError:
        raise HTTPException(400, 'Identificador do envio inválido')
    if not confirmed:
        raise HTTPException(400, 'Confirme destinatário e conteúdo antes de enviar')
    try:
        visible_text = message_text(text, formatting)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not visible_text.strip() and image is None:
        raise HTTPException(400, 'Escreva uma mensagem ou selecione uma imagem')
    if len(visible_text.encode('utf-16-le')) // 2 > (1024 if image else 4096):
        raise HTTPException(400, 'Texto visível acima do limite: 1024 com imagem ou 4096 sem imagem')
    parse_mode = 'html' if formatting == 'html' else None
    photo = None
    if image is not None:
        from PIL import Image, UnidentifiedImageError
        data = await image.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(413, 'Imagem acima de 5 MB')
        try:
            with Image.open(io.BytesIO(data)) as decoded:
                if decoded.format not in {'JPEG', 'PNG'} or decoded.width * decoded.height > 20_000_000:
                    raise ValueError()
                decoded.verify()
            photo = io.BytesIO(data)
            photo.name = 'imagem.png' if data.startswith(b'\x89PNG') else 'imagem.jpg'
        except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
            raise HTTPException(400, 'Imagem inválida. Use PNG ou JPEG de até 20 megapixels.')
    if lock.locked():
        raise HTTPException(409, 'Outra operação está em andamento')
    async with lock:
        with Session() as db:
            item = db.get(Lead, lead_id)
            if item is None or item.status == 'deleted':
                raise HTTPException(404, 'Contato não encontrado ou excluído')
            previous = db.get(SendAttempt, request_id)
            if previous:
                if previous.lead_id != lead_id:
                    raise HTTPException(409, 'Identificador já usado para outro contato')
                if previous.state == 'sent':
                    return {'state': 'sent', 'duplicate_prevented': True}
                raise HTTPException(409, 'Envio já registrado. Confira a conversa antes de tentar novamente.')
            if item.blocked:
                raise HTTPException(403, 'Contato bloqueado para novos envios')
            if item.status in {'sent', 'unknown', 'sending'}:
                raise HTTPException(409, 'Contato já enviado ou com resultado incerto. Confira a conversa no Telegram.')
            control = db.get(SendControl, 1)
            if control and control.next_allowed:
                wait = (control.next_allowed.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds()
                if wait > 0:
                    raise HTTPException(429, 'Aguarde antes do próximo envio.', headers={'Retry-After': str(int(wait)+1)})
            me = await client.get_me()
            if me is None:
                raise HTTPException(401, 'Conecte sua conta Telegram')
            try:
                target = await client.get_entity(item.username)
            except (ValueError, errors.UsernameInvalidError, errors.UsernameNotOccupiedError):
                raise HTTPException(400, 'Username não encontrado. Nenhum envio realizado.')
            except errors.FloodWaitError as exc:
                set_cooldown(db, exc.seconds)
                db.commit()
                raise
            if not isinstance(target, User) or target.bot or target.id == me.id:
                raise HTTPException(400, 'O destinatário deve ser uma pessoa, não bot, grupo ou a própria conta')
            if db.query(Lead).filter(Lead.status == 'deleted', Lead.telegram_id == str(target.id)).first():
                raise HTTPException(403, 'Esse usuário foi excluído da lista. Nenhum envio realizado.')
            if item.telegram_id and str(target.id) != item.telegram_id:
                raise HTTPException(409, 'O username aponta para um ID diferente da planilha. Nenhum envio realizado.')
            attempt = SendAttempt(id=request_id, lead_id=lead_id, state='sending')
            db.add(attempt)
            item.status = 'unknown'  # conservado após queda do processo/rede; não repetimos automaticamente
            db.commit()
            try:
                if photo is not None:
                    await client.send_file(target, photo, caption=text, parse_mode=parse_mode)
                else:
                    await client.send_message(target, text, parse_mode=parse_mode)
            except errors.FloodWaitError as exc:
                attempt.state = 'failed'
                item.status = 'pending'
                set_cooldown(db, exc.seconds)
                db.commit()
                raise
            except errors.PeerFloodError:
                attempt.state = 'failed'
                item.status = 'pending'
                set_cooldown(db, 24 * 60 * 60)
                db.commit()
                raise HTTPException(429, 'Telegram restringiu os envios. Pare e verifique a conta; o sistema não tentará novamente.', headers={'Retry-After': '86400'})
            except (errors.UserPrivacyRestrictedError, errors.UserIsBlockedError, errors.YouBlockedUserError, errors.ChatWriteForbiddenError):
                attempt.state = 'failed'
                item.status = 'pending'
                item.blocked = True
                db.commit()
                raise HTTPException(403, 'Telegram não permite enviar a esse contato. Contato bloqueado no sistema.')
            except Exception:
                attempt.state = 'unknown'
                db.commit()
                raise HTTPException(502, 'Resultado incerto. Confira a conversa no Telegram; não repita o envio automaticamente.')
            attempt.state = 'sent'
            item.status = 'sent'
            item.telegram_id = str(target.id)
            item.last_contact = datetime.now(timezone.utc)
            set_cooldown(db, 10)
            db.commit()
            return {'state': 'sent', 'lead': lead_dict(item)}
