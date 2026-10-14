import io
import pandas as pd
import pytest
from app.audit import parse_ids, compare


def workbook(values, column='Telegram ID'):
    out=io.BytesIO()
    pd.DataFrame({column:values}).to_excel(out,index=False)
    return out.getvalue()


def test_import_deduplicates_and_rejects_invalid():
    ids,meta=parse_ids(workbook(['123','123','456','bad','-5','0']))
    assert ids==[123,456]
    assert meta['invalid']==3
    assert meta['duplicates']==1


def test_unknown_column_requires_selection():
    with pytest.raises(ValueError): parse_ids(workbook(['123'],'Membro'))
    assert parse_ids(workbook(['123'],'Membro'),'Membro')[0]==[123]


def test_match_without_username_and_missing():
    result=compare([1,2,3],{1:{'name':'Ana','username':None},2:{'name':'Bia','username':'bia'},9:{'name':'Outra'}})
    assert result['metrics']=={'imported':3,'private_dialogs':3,'found':2,'not_found':1,'with_username':1,'without_username':1,'match_percent':66.67}
    assert result['rows'][0]['matched'] is True
    assert result['rows'][2]['name']==''


def test_empty():
    assert compare([],{})['metrics']['match_percent']==0


def test_ambiguous_columns_require_explicit_choice():
    out=io.BytesIO()
    pd.DataFrame({'ID':['123'],'User ID':['456']}).to_excel(out,index=False)
    with pytest.raises(ValueError): parse_ids(out.getvalue())
    assert parse_ids(out.getvalue(),'ID')[0]==[123]


def test_large_ids_keep_precision():
    ids,_=parse_ids(workbook(['9007199254740993','9223372036854775808']))
    assert ids==[9007199254740993]
    assert compare(ids,{})['rows'][0]['id']=='9007199254740993'
