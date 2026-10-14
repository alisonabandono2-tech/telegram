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


def import_contacts(client):
    out=io.BytesIO()
    pd.DataFrame({'Nome':['Ana','Bia','Sem username','Ana duplicada'],'@usuario':['@alice_test','@bia_test','','@ALICE_TEST'],'ID':['11','22','33','11']}).to_excel(out,index=False)
    r=client.post('/leads/import',files={'file':('members.xlsx',out.getvalue())})
    assert r.status_code==200,r.text
    return r.json(),client.get('/leads').json()


def send(client,uid,request_id=None,**kwargs):
    import uuid
    data={'text':'Olá pessoa','confirmed':'true','request_id':request_id or str(uuid.uuid4())}
    data.update(kwargs.pop('data',{}))
    return client.post(f'/leads/{uid}/send',data=data,**kwargs)


def prepare_sender(fake):
    fake.get_entity=AsyncMock(return_value=User(id=11,first_name='Ana',username='alice_test'))
    fake.send_message=AsyncMock()
    fake.send_file=AsyncMock()


def test_contacts_import_repeat_and_single_send_idempotency(api):
    import uuid
    client,fake,module=api
    prepare_sender(fake)
    info,leads=import_contacts(client)
    assert info['added']==2 and info['invalid']==1 and info['duplicates']==1
    info,_=import_contacts(client)
    assert info['added']==0 and info['already_imported']==2
    rid=str(uuid.uuid4())
    r=send(client,leads[0]['id'],rid)
    assert r.status_code==200,r.text
    assert fake.send_message.await_count==1
    assert fake.send_message.await_args.kwargs['parse_mode'] is None
    assert send(client,leads[0]['id'],rid).json()['duplicate_prevented'] is True
    assert fake.send_message.await_count==1
    rows=client.get('/leads').json()
    assert rows[0]['status']=='sent' and rows[0]['last_contact']
    assert rows[1]['status']=='pending'
    assert send(client,leads[0]['id']).status_code==409
    assert send(client,leads[1]['id']).status_code==429


def test_send_confirmation_block_and_id_mismatch(api):
    client,fake,module=api
    prepare_sender(fake)
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    assert send(client,uid,data={'confirmed':'false'}).status_code==400
    fake.get_entity.return_value=User(id=999,username='alice_test')
    assert send(client,uid).status_code==409
    assert fake.send_message.await_count==0
    assert client.post(f'/leads/{uid}/block',json={'blocked':True}).status_code==200
    assert send(client,uid).status_code==403


def test_image_validation_and_caption(api):
    from PIL import Image
    client,fake,module=api
    prepare_sender(fake)
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    assert send(client,uid,files={'image':('fake.png',b'not an image','image/png')}).status_code==400
    img=io.BytesIO()
    Image.new('RGB',(4,4),'blue').save(img,format='PNG')
    assert send(client,uid,data={'text':'a'*1025},files={'image':('photo.png',img.getvalue(),'image/png')}).status_code==400
    r=send(client,uid,files={'image':('photo.png',img.getvalue(),'image/png')})
    assert r.status_code==200,r.text
    fake.send_file.assert_awaited_once()
    assert fake.send_file.await_args.kwargs['caption']=='Olá pessoa'
    assert fake.send_message.await_count==0


def test_send_flood_wait_persisted_and_unknown_result(api):
    client,fake,module=api
    prepare_sender(fake)
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    fake.send_message.side_effect=errors.FloodWaitError(request=None,capture=20)
    r=send(client,uid)
    assert r.status_code==429 and r.headers['retry-after']=='20'
    r=send(client,uid)
    assert r.status_code==429
    assert fake.send_message.await_count==1
    with module.Session() as db:
        control=db.get(module.SendControl,1)
        control.next_allowed=datetime(2000,1,1,tzinfo=timezone.utc)
        db.commit()
    fake.send_message.side_effect=ConnectionError('fictional connection loss')
    assert send(client,uid).status_code==502
    assert client.get('/leads').json()[0]['status']=='unknown'
    assert send(client,uid).status_code==409
    assert fake.send_message.await_count==2


def test_send_rejects_bot_and_privacy_restriction(api):
    client,fake,module=api
    prepare_sender(fake)
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    fake.get_entity.return_value=User(id=11,bot=True)
    assert send(client,uid).status_code==400
    fake.get_entity.return_value=User(id=11)
    fake.send_message.side_effect=errors.UserPrivacyRestrictedError(request=None)
    assert send(client,uid).status_code==403
    assert client.get('/leads').json()[0]['blocked'] is True
    assert send(client,uid).status_code==403
    assert fake.send_message.await_count==1


def test_delete_confirmation_persistence_import_and_no_send(api):
    client,fake,module=api
    prepare_sender(fake)
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    assert client.post(f'/leads/{uid}/delete',json={'confirmed':False}).status_code==400
    assert len(client.get('/leads').json())==2
    r=client.post(f'/leads/{uid}/delete',json={'confirmed':True})
    assert r.status_code==200 and r.json()['removed']==1
    assert [x['username'] for x in client.get('/leads').json()]==['bia_test']
    info,rows=import_contacts(client)
    assert info['added']==0 and info['excluded']==1 and info['already_imported']==1
    assert len(rows)==1
    assert send(client,uid).status_code==404
    assert client.post(f'/leads/{uid}/block',json={'blocked':False}).status_code==404
    assert fake.get_entity.await_count==0 and fake.send_message.await_count==0
    assert client.post(f'/leads/{uid}/delete',json={'confirmed':True}).json()['removed']==0
    with module.Session() as db:
        assert db.get(module.Lead,uid).status=='deleted'


def test_delete_excludes_known_id_with_changed_username_and_keeps_history(api):
    client,fake,module=api
    prepare_sender(fake)
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    assert send(client,uid).status_code==200
    assert client.post(f'/leads/{uid}/delete',json={'confirmed':True}).status_code==200
    out=io.BytesIO()
    pd.DataFrame({'Nome':['Ana'],'username':['alice_changed'],'ID':['11']}).to_excel(out,index=False)
    r=client.post('/leads/import',files={'file':('leads.xlsx',out.getvalue())})
    assert r.status_code==200 and r.json()['excluded']==1 and r.json()['added']==0
    with module.Session() as db:
        assert db.query(module.SendAttempt).filter_by(lead_id=uid,state='sent').count()==1


def test_delete_access_and_busy_guard(api):
    client,fake,module=api
    _,leads=import_contacts(client)
    uid=leads[0]['id']
    client.portal.call(module.lock.acquire)
    try:
        assert client.post(f'/leads/{uid}/delete',json={'confirmed':True}).status_code==409
    finally:
        client.portal.call(module.lock.release)
    assert len(client.get('/leads').json())==2
    assert client.post('/leads/99999/delete',json={'confirmed':True}).status_code==404
    client.headers['Authorization']='Bearer wrong'
    assert client.post(f'/leads/{uid}/delete',json={'confirmed':True}).status_code==401
