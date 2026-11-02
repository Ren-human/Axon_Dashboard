"""Local date-only aggregation of the selected report's verified raw snapshot.

No resident row, ID, note or path is returned by this module.
"""
from collections import Counter
import csv
from datetime import date, datetime
import hashlib
from pathlib import Path

EVENTS = {'referral':'referral_date','intake':'intake_date','admission':'admission_date'}


class ActivitySourceError(ValueError):
    """Only fixed, safe source explanations may cross the worker boundary."""


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            hasher.update(block)
    return hasher.hexdigest()


def monthly_activity(path, metadata):
    expected = metadata['input_sha256']
    if not isinstance(expected,str) or digest(path) != expected:
        raise ActivitySourceError('The raw snapshot does not match this report; monthly activity withheld.')
    end = date.fromisoformat(str(metadata['as_of']))
    fiscal = metadata.get('fiscal_year')
    start = date(int(fiscal),1,1) if fiscal is not None else None
    counts = Counter()
    exclusions = {event:dict(missing=0,invalid=0) for event in EVENTS}
    ids = set()
    earliest = None
    with Path(path).open('r',encoding='utf-8-sig',newline='') as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if not {'resident_id',*EVENTS.values()} <= set(headers) or len(headers) != len(set(headers)):
            raise ActivitySourceError('Monthly activity source schema is invalid.')
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ActivitySourceError('Monthly activity source has malformed records.')
            rid = row['resident_id'].strip()
            if not rid or rid in ids:
                raise ActivitySourceError('Monthly activity requires unique nonempty source IDs.')
            ids.add(rid)
            for event, column in EVENTS.items():
                value = row[column].strip()
                if not value:
                    exclusions[event]['missing'] += 1
                    continue
                parsed = None
                for pattern in ('%Y-%m-%d','%m/%d/%Y'):
                    try:
                        parsed = datetime.strptime(value,pattern).date()
                        break
                    except ValueError:
                        pass
                if parsed is None:
                    exclusions[event]['invalid'] += 1
                    continue
                if parsed > end or (start is not None and parsed < start):
                    continue
                earliest = min(earliest,parsed) if earliest else parsed
                counts[(parsed.strftime('%Y-%m'),event)] += 1
    if digest(path) != expected:
        raise ActivitySourceError('Raw snapshot changed during aggregation; results withheld.')
    start = start or earliest or end.replace(day=1)
    month = start.replace(day=1)
    rows = []
    while month <= end:
        for event in EVENTS:
            rows.append([month.strftime('%Y-%m'),event,counts[(month.strftime('%Y-%m'),event)]])
        if len(rows) > 500:
            raise ActivitySourceError('Monthly activity row limit exceeded.')
        if month.year == 9999 and month.month == 12:
            break
        month = date(month.year+(month.month==12),month.month%12+1,1)
    return dict(columns=['month','event','n'],rows=rows), exclusions
