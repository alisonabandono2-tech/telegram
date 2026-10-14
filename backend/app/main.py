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
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, Column, Integer, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
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
engine = create_engine(settings.database_url, pool_pre_ping=True)
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
client = TelegramClient(str(session_path / 'account'), settings.telegram_api_id, settings.telegram_api_hash.get_secret_value(), flood_sleep_threshold=0)
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


app = FastAPI(title='Telegram CRM — Auditoria', lifespan=lifespan)
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
