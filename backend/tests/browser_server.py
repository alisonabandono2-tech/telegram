"""Servidor exclusivo de teste de navegador. Não se conecta ao Telegram real."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import telethon
from telethon import errors
from telethon.tl.types import User

fixture_directory = tempfile.TemporaryDirectory(prefix='telegram-browser-')
os.environ.update(DATABASE_URL='sqlite:///'+str(Path(fixture_directory.name)/'test.db'), TELEGRAM_API_ID='12345', TELEGRAM_API_HASH='fictional-hash', APP_TOKEN='fictional-token-for-tests-only-1234', SESSION_DIR=str(Path(fixture_directory.name)/'sessions'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class FakeTelegram:
    def __init__(self,*args,**kwargs):
        self.authorized=False
        self.connect=AsyncMock()
        self.disconnect=AsyncMock()
    async def get_me(self):
        return User(id=100,first_name='Conta fictícia') if self.authorized else None
    async def send_code_request(self,phone):
        return SimpleNamespace(phone_code_hash='fictional-code-hash')
    async def sign_in(self,**kwargs):
        if 'code' in kwargs:
            raise errors.SessionPasswordNeededError(request=None)
        self.authorized=True
    async def get_entity(self,username):
        return User(id=11 if username=='alice_test' else 22,first_name='Contato fictício',username=username)
    async def send_message(self,*args,**kwargs):
        return SimpleNamespace(id=1)
    async def send_file(self,*args,**kwargs):
        return SimpleNamespace(id=2)


if __name__=='__main__':
    telethon.TelegramClient=FakeTelegram
    import uvicorn
    from app.main import app
    @app.get('/__test__/fixture')
    def fixture_marker():
        return {'fixture': os.environ.get('TEST_RUN_MARKER','fictional-browser-test')}
    uvicorn.run(app,host='127.0.0.1',port=8000,access_log=False)
