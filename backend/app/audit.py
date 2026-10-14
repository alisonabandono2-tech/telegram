import io
import re
import zipfile
import pandas as pd


def parse_ids(data: bytes, column: str | None = None):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('Conteúdo descompactado acima de 100 MB')
    frame = pd.read_excel(io.BytesIO(data), dtype=str)
    candidates = [str(c) for c in frame.columns if re.sub(r'[^a-z0-9]', '', str(c).lower()) in {'id', 'telegramid', 'userid', 'idtelegram', 'idusuario'}]
    if column is None:
        if len(candidates) != 1:
            raise ValueError('Selecione a coluna de Telegram ID. Colunas: ' + ', '.join(map(str, frame.columns)))
        column = candidates[0]
    if column not in frame.columns:
        raise ValueError('Coluna inexistente')
    ids, invalid, duplicates = [], 0, 0
    seen = set()
    for value in frame[column]:
        s = str(value).strip()
        if not re.fullmatch(r'[0-9]+(?:\.0)?', s):
            invalid += 1
            continue
        uid = int(s.split('.')[0])
        if uid <= 0 or uid > 2**63 - 1:
            invalid += 1
        elif uid in seen:
            duplicates += 1
        else:
            seen.add(uid)
            ids.append(uid)
    return ids, {'column': column, 'rows': len(frame), 'invalid': invalid, 'duplicates': duplicates}


def compare(ids, dialogs):
    rows = []
    for uid in ids:
        d = dialogs.get(uid)
        rows.append({'id': str(uid), 'name': d.get('name', '') if d else '', 'username': d.get('username') if d else None, 'matched': d is not None, 'last_interaction': d.get('last_interaction') if d else None})
    found = sum(r['matched'] for r in rows)
    with_username = sum(bool(r['username']) for r in rows if r['matched'])
    return {'rows': rows, 'metrics': {'imported': len(ids), 'private_dialogs': len(dialogs), 'found': found, 'not_found': len(ids)-found, 'with_username': with_username, 'without_username': found-with_username, 'match_percent': round(found / len(ids)*100, 2) if ids else 0}}
