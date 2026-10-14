import importlib
import io
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from telethon import errors
from telethon.tl.types import User, Chat


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ.get('TEST_DATABASE_URL', 'sqlite:///'+str(tmp_path/'test.db')))
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'fictional-hash')
    monkeypatch.setenv('APP_TOKEN', 'fictional-token-for-tests-only-1234')
    monkeypatch.setenv('SESSION_DIR', str(tmp_path/'sessions'))
    import telethon
    fake=SimpleNamespace(connect=AsyncMock(),disconnect=AsyncMock(),is_user_authorized=AsyncMock(return_value=True),send_code_request=AsyncMock(return_value=SimpleNamespace(phone_code_hash='fake-hash')),sign_in=AsyncMock())
    async def dialogs():
        for entity in [User(id=11,first_name='=FAKE()',username=None),User(id=22,first_name='Bia',username='bia'),User(id=33,bot=True),User(id=44,is_self=True),Chat(id=55,title='Grupo',photo=None,participants_count=1,date=datetime.now(timezone.utc),version=1)]:
            yield SimpleNamespace(entity=entity,date=datetime(2025,1,1,tzinfo=timezone.utc))
    async def get_me():
        return SimpleNamespace(id=100) if await fake.is_user_authorized() else None
    fake.get_me=get_me
    fake.iter_dialogs=dialogs
    monkeypatch.setattr(telethon,'TelegramClient',lambda *a,**k:fake)
    import app.main
    module=importlib.reload(app.main)
    with TestClient(module.app) as client:
        client.headers['Authorization']='Bearer fictional-token-for-tests-only-1234'
        yield client,fake,module
    module.Base.metadata.drop_all(module.engine)


def spreadsheet():
    out=io.BytesIO()
    pd.DataFrame({'Telegram ID':['11','22','99']}).to_excel(out,index=False)
    return out.getvalue()


def test_audit_persistence_exports_and_access(api):
    client,fake,module=api
    assert client.get('/health').status_code==200
    r=client.post('/audit',files={'file':('members.xlsx',spreadsheet())})
    assert r.status_code==200, r.text
    result=r.json()
    assert result['metrics']['found']==2
    assert result['metrics']['private_dialogs']==2
    assert result['rows'][0]['username'] is None
    assert client.get('/audit/latest').json()['audit_id']==result['audit_id']
    csv=client.get(f"/audit/{result['audit_id']}/export?format=csv")
    assert csv.status_code==200
    assert "'=FAKE()" in csv.text
    excel=client.get(f"/audit/{result['audit_id']}/export?format=xlsx")
    assert len(pd.read_excel(io.BytesIO(excel.content)))==3
    assert client.get('/audit/progress').json()['state']=='complete'
    client.headers['Authorization']='Bearer wrong'
    assert client.get('/audit/latest').status_code==401


def test_login_with_2fa(api):
    client,fake,module=api
    fake.is_user_authorized.return_value=False
    assert client.post('/auth/code',json={'code':'123'}).status_code==400
    assert client.post('/auth/phone',json={'phone':'+5511000000000'}).json()['state']=='code_required'
    fake.sign_in.side_effect=errors.SessionPasswordNeededError(request=None)
    assert client.post('/auth/code',json={'code':'12345'}).json()['state']=='password_required'
    fake.sign_in.side_effect=None
    assert client.post('/auth/password',json={'password':'fictional'}).json()['state']=='authorized'
    assert not module.login


def test_flood_wait_and_expired_session(api):
    client,fake,module=api
    async def limited():
        raise errors.FloodWaitError(request=None,capture=7)
        yield
    fake.iter_dialogs=limited
    r=client.post('/audit',files={'file':('members.xlsx',spreadsheet())})
    assert r.status_code==429
    assert r.headers['retry-after']=='7'
    assert client.get('/audit/latest').json() is None
    fake.is_user_authorized.return_value=False
    assert client.post('/audit',files={'file':('members.xlsx',spreadsheet())}).status_code==401


def test_invalid_code_and_password_out_of_order(api):
    client,fake,module=api
    assert client.post('/auth/password',json={'password':'fictional'}).status_code==400
    fake.is_user_authorized.return_value=False
    client.post('/auth/phone',json={'phone':'+5511000000000'})
    fake.sign_in.side_effect=errors.PhoneCodeExpiredError(request=None)
    assert client.post('/auth/code',json={'code':'12345'}).status_code==400
    assert 'phone_code_hash' not in client.get('/auth/status').text
