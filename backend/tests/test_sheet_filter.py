import importlib.util
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook
from app.leads import parse_leads

spec=importlib.util.spec_from_file_location('sheet_filter',Path(__file__).resolve().parents[2]/'filtrar-planilha.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_requested_filters_and_common_names():
    frame=pd.DataFrame([
        {'Nome':'Rafael Reis','@usuario':'@personname','ID':'1'},
        {'Nome':'Outro nome','@usuario':'@rafinha123','ID':'2'},
        {'Nome':'Fernando','@usuario':'@fernando_1win','ID':'3'},
        {'Nome':'Contato','@usuario':'@slts1234','ID':'4'},
        {'Nome':'Suporte','@usuario':'@suportename','ID':'5'},
        {'Nome':'Sem usuario','@usuario':'','ID':'6'},
        {'Nome':'Betania','@usuario':'@betania123','ID':'7'},
        {'Nome':'Rafael Barbosa','@usuario':'@rafaelbarbosa','ID':'8'},
        {'Nome':'Duplicado','@usuario':'@RAFAELBARBOSA','ID':'8'},
        {'Nome':'Beto Designer','@usuario':'@betodesigner','ID':'9'},
    ])
    result,counts=module.clean(frame)
    assert result['Nome'].tolist()==['Betania','Rafael Barbosa']
    assert counts=={'total':10,'sem_username_valido':1,'nomes_solicitados':2,'servicos_spam_aparente':4,'duplicatas':1,'mantidos':2}


def test_export_preserves_literal_text_and_can_be_imported(tmp_path):
    frame=pd.DataFrame([{'Nome':'=FAKE()','@usuario':'@personname','ID':'9007199254740993'}])
    output=tmp_path/'filtered.xlsx'
    module.write_workbook(frame,output)
    book=load_workbook(output)
    assert book['Contatos']['A2'].data_type=='s'
    assert book['Contatos']['C2'].value=='9007199254740993'
    rows,meta=parse_leads(output.read_bytes(),output.name)
    assert len(rows)==1 and meta['invalid']==0
    assert rows[0]['telegram_id']=='9007199254740993'
