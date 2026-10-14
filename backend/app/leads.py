"""Importação de contatos públicos; nunca resolve IDs isolados."""
import io
import re
import zipfile
import pandas as pd


def parse_leads(data: bytes, filename: str):
    if filename.lower().endswith('.xlsx'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(f.file_size for f in z.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Planilha muito grande')
        frame = pd.read_excel(io.BytesIO(data), dtype=str).fillna('')
    elif filename.lower().endswith('.csv'):
        frame = pd.read_csv(io.BytesIO(data), dtype=str, sep=None, engine='python').fillna('')
    else:
        raise ValueError('Use XLSX ou CSV')
    columns = {re.sub(r'[^a-z0-9]', '', str(c).lower()): c for c in frame.columns}
    username_col = next((columns[k] for k in ['usuario', 'username', 'telegramusername'] if k in columns), None)
    if username_col is None:
        raise ValueError('Coluna de username não encontrada. Use @usuario ou username.')
    name_col = next((columns[k] for k in ['nome', 'name'] if k in columns), None)
    id_col = next((columns[k] for k in ['id', 'telegramid', 'userid'] if k in columns), None)
    rows, seen, invalid, duplicates = [], set(), 0, 0
    for _, row in frame.iterrows():
        username = str(row[username_col]).strip().lstrip('@')
        username = re.sub(r'^https?://(?:www\.)?t\.me/', '', username, flags=re.I).rstrip('/')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', username):
            invalid += 1
            continue
        if username.lower() in seen:
            duplicates += 1
            continue
        seen.add(username.lower())
        raw_id = str(row[id_col]).strip() if id_col else ''
        tid = str(int(raw_id.split('.')[0])) if re.fullmatch(r'[1-9][0-9]*(?:\.0)?', raw_id) else None
        rows.append({'username': username.lower(), 'name': str(row[name_col]).strip()[:200] if name_col else '', 'telegram_id': tid})
    return rows, {'rows': len(frame), 'valid': len(rows), 'invalid': invalid, 'duplicates': duplicates}
