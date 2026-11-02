"""Local single-user recording and recoverable publication. No Streamlit imports.

Only initialize() and submit_record() write reports. current.json is the sole
activation point; the seed CSV and all historical databases remain untouched.
"""
import argparse
from contextlib import contextmanager
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import uuid
import warnings

import metrics
import duckdb_store

ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config_path():
    return Path(os.environ.get('HARBOURVIEW_CONFIG', ROOT / 'report_config.json')).expanduser()


def load_config(path=None):
    path = Path(path or config_path()).resolve()
    if not path.is_file():
        raise ValueError('录入未配置。复制 report_config.example.json 为 report_config.json，确认数据源和报告参数后运行初始化命令。')
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg, dict):
        raise ValueError('配置必须是 JSON 对象。')
    for key in ('source_csv', 'version_root'):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ValueError(f'请在配置中明确指定 {key}。')
        p = Path(cfg[key]).expanduser()
        cfg[key] = str((path.parent / p).resolve() if not p.is_absolute() else p.resolve())
    p = cfg.get('report', {})
    required = {'as_of', 'fiscal_year', 'capacity', 'followup_anchor', 'occupancy_start'}
    if not isinstance(p, dict) or set(p) != required:
        raise ValueError('report 必须明确包含 as_of、fiscal_year、capacity、followup_anchor、occupancy_start。')
    try:
        date.fromisoformat(p['as_of'])
        date.fromisoformat(p['occupancy_start'])
        if date.fromisoformat(p['occupancy_start']) > date.fromisoformat(p['as_of']):
            raise ValueError('入住率起始日期晚于截止日期')
        if p['fiscal_year'] is not None and (type(p['fiscal_year']) is not int or not 1 <= p['fiscal_year'] <= 9998):
            raise ValueError('财年无效')
        if type(p['capacity']) is not int or p['capacity'] <= 0:
            raise ValueError('容量必须为正整数')
        if p['followup_anchor'] not in ('admission', 'discharge'):
            raise ValueError('随访起点无效')
        if p['fiscal_year'] is not None:
            cutoff = min(date.fromisoformat(p['as_of']), date(p['fiscal_year'], 12, 31))
            if cutoff < date(p['fiscal_year'], 1, 1) or date.fromisoformat(p['occupancy_start']) > cutoff:
                raise ValueError('财年与报告日期不一致')
    except (TypeError, ValueError) as exc:
        raise ValueError(f'报告参数无效：{exc}') from exc
    return cfg


def parameters(cfg):
    p = cfg['report']
    return dict(as_of=date.fromisoformat(p['as_of']), fiscal_year=p['fiscal_year'],
                capacity=p['capacity'], anchor=p['followup_anchor'],
                start=date.fromisoformat(p['occupancy_start']))


def version_dir(cfg, version):
    if not isinstance(version, str) or not re.fullmatch('[0-9a-f]{32}', version):
        raise ValueError('Invalid version identifier')
    root = (Path(cfg['version_root']) / 'versions').resolve()
    p = (root / version).resolve()
    if p.parent != root:
        raise ValueError('Version path escapes configured storage')
    return p


def current(cfg):
    path = Path(cfg['version_root']) / 'current.json'
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not {'version', 'params', 'source_csv'} <= set(manifest):
        raise ValueError('当前版本清单无效；请恢复完整清单。')
    directory = version_dir(cfg, manifest['version'])
    stored = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if stored != manifest:
        raise ValueError('当前版本清单与版本目录不一致；请恢复完整清单。')
    if manifest['params'] != cfg['report'] or manifest['source_csv'] != cfg['source_csv']:
        raise ValueError('配置与启用版本不一致。请恢复该版本的配置；不同报告参数应使用独立版本存储目录。')
    if not (directory / 'raw.csv').is_file() or not (directory / 'report.duckdb').is_file():
        raise ValueError('启用版本文件缺失；请恢复完整版本目录。')
    return manifest


def active_paths(cfg, manifest):
    directory = version_dir(cfg, manifest['version'])
    return directory / 'raw.csv', directory / 'report.duckdb'


def read_raw(path):
    data = Path(path).read_bytes()
    rows, headers = metrics._load_csv_bytes(data)
    # Validate via the same loader; preserve the original, untrimmed cells on write.
    original = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline='')))
    if '_row' in headers:
        raise ValueError('原始列 _row 与计算程序内部字段冲突，需先人工处理。')
    return data, original, rows, headers


def source_snapshot(cfg):
    manifest = current(cfg)
    if manifest is None:
        raise ValueError('录入尚未初始化。请先运行 python report_versions.py initialize --config report_config.json。')
    raw, _ = active_paths(cfg, manifest)
    data, original, rows, headers = read_raw(raw)
    if hashlib.sha256(data).hexdigest() != manifest['input_sha256']:
        raise ValueError('启用原始数据的哈希发生变化；请恢复该版本，不会继续追加。')
    if not os.access(raw.parent, os.W_OK) or not os.access(Path(cfg['version_root']), os.W_OK):
        raise ValueError('配置的版本存储目录不可写。')
    return manifest, data, original, rows, headers


def normalize_record(cfg, values, rows, headers):
    record = {c: '' for c in headers}
    for c in metrics.REQUIRED:
        value = values.get(c, '')
        if isinstance(value, date):
            value = value.isoformat()
        record[c] = str(value if value is not None else '').strip()
    if not record['resident_id']:
        raise ValueError('居民 ID 不能为空。')
    if record['resident_id'] in {r['resident_id'] for r in rows}:
        raise ValueError('居民 ID 已存在（按加载规则去除首尾空白后比较）。')
    for c in metrics.DATE_COLS:
        metrics.parse_date(record[c])
    for c, allowed in {
        'current_status': metrics.ACTIVE | metrics.EXITED | {'not_admitted', ''},
        'fee_waived': {'', 'true', 'false'},
        'followup_6m': metrics.OUTCOMES, 'followup_12m': metrics.OUTCOMES,
    }.items():
        record[c] = record[c].lower()
        if record[c] not in allowed:
            raise ValueError(f'{c} 不是允许的选项。')
    if record['entrance_fee']:
        try:
            fee = float(record['entrance_fee'])
            if not math.isfinite(fee) or fee < 0:
                raise ValueError()
        except (ValueError, OverflowError) as exc:
            raise ValueError('入场费用必须为空或有限非负数。') from exc
    if record['bed_capacity'] != str(cfg['report']['capacity']):
        raise ValueError('床位容量必须使用已确认的报告配置，不能通过居民表单更改。')
    return record


def preview_record(cfg, values):
    manifest, data, _, rows, headers = source_snapshot(cfg)
    record = normalize_record(cfg, values, rows, headers)
    # Reuse pipeline quality rules on the proposed resident, never duplicate them.
    result = metrics.calculate([{**record, '_row': len(rows) + 2}], **parameters(cfg))
    payload = dict(record=record, warnings=result['data_quality_issues'],
                   base_version=manifest['version'], source_hash=hashlib.sha256(data).hexdigest(),
                   config_hash=digest(cfg), metrics_hash=file_hash(metrics.__file__),
                   params=cfg['report'], submission_id=uuid.uuid4().hex)
    payload['preview_hash'] = digest(payload)
    return payload


@contextmanager
def publication_lock(cfg):
    root = Path(cfg['version_root'])
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.publish.lock'
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError('已有发布操作或遗留锁；请等待。若程序异常退出，按 README 恢复锁后重试。') from exc
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'pid': os.getpid(), 'created_at': datetime.now(timezone.utc).isoformat()}))
        yield
    finally:
        try:
            lock.unlink()
        except OSError as exc:
            # A cleanup failure after activation must not misreport a saved record as unsaved.
            warnings.warn(f'发布锁清理失败，请按 README 处理：{exc}', RuntimeWarning)


def atomic_json(path, data):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class PublicationError(RuntimeError):
    def __init__(self, stage, directory, cause):
        self.stage, self.candidate = stage, str(directory)
        super().__init__(f'失败阶段：{stage}。记录未启用，当前版本保持不变，可重试。候选目录：{directory}。原因：{cause}')


def publish(cfg, write_candidate, submission_id, resident_id, previous):
    directory = version_dir(cfg, uuid.uuid4().hex)
    stage = '生成候选原始数据'
    try:
        directory.mkdir(parents=True, exist_ok=False)
        write_candidate(directory / 'raw.csv')
        stage = '计算'
        result = metrics.calculate_file(directory / 'raw.csv', **parameters(cfg))
        stage = '导出汇总'
        metrics.export_result(result, directory / 'aggregates')
        stage = '导入 DuckDB'
        duckdb_store.build(directory / 'aggregates', directory / 'report.duckdb')
        stage = '校验新数据库'
        duckdb_store.validate_database(directory / 'report.duckdb', directory / 'aggregates')
        metadata = result['metadata']
        manifest = dict(schema=1, version=directory.name, previous_version=previous,
                        submission_id=submission_id, resident_id=resident_id,
                        params=cfg['report'], source_csv=cfg['source_csv'],
                        input_sha256=metadata['input_sha256'], db_sha256=file_hash(directory / 'report.duckdb'),
                        metrics_version=metadata['metrics_version'], metrics_sha256=file_hash(metrics.__file__),
                        report_as_of=metadata['as_of'], created_at=datetime.now(timezone.utc).isoformat())
        atomic_json(directory / 'manifest.json', manifest)
        stage = '启用版本'
        atomic_json(Path(cfg['version_root']) / 'current.json', manifest)
        return manifest
    except Exception as exc:
        raise PublicationError(stage, directory, exc) from exc


def initialize(cfg):
    with publication_lock(cfg):
        if current(cfg) is not None:
            raise ValueError('已有启用版本，拒绝覆盖或重新初始化；不同报告请使用新的 version_root。')
        source = Path(cfg['source_csv'])
        data, _, _, _ = read_raw(source)
        return publish(cfg, lambda p: p.write_bytes(data), uuid.uuid4().hex, None, None)


def find_submission(cfg, manifest, submission_id):
    seen = set()
    while manifest:
        if manifest['version'] in seen:
            raise ValueError('版本历史存在循环。')
        seen.add(manifest['version'])
        if manifest['submission_id'] == submission_id:
            return manifest
        previous = manifest.get('previous_version')
        manifest = (json.loads((version_dir(cfg, previous) / 'manifest.json').read_text(encoding='utf-8'))
                    if previous else None)
    return None


def submit_record(cfg, preview):
    with publication_lock(cfg):
        supplied = {k: v for k, v in preview.items() if k != 'preview_hash'}
        if digest(supplied) != preview.get('preview_hash'):
            raise ValueError('预览内容已变化，请重新预览。')
        if digest(cfg) != preview['config_hash'] or file_hash(metrics.__file__) != preview['metrics_hash']:
            raise ValueError('报告配置或计算程序已变化，请重新预览。')
        active = current(cfg)
        if active is None:
            raise ValueError('没有启用版本，请先初始化。')
        receipt = find_submission(cfg, active, preview['submission_id'])
        if receipt:
            return dict(receipt=receipt, active=active, already_applied=True)
        manifest, data, original, rows, headers = source_snapshot(cfg)
        _, active_db = active_paths(cfg, manifest)
        if file_hash(active_db) != manifest['db_sha256']:
            raise ValueError('启用数据库的哈希发生变化，请恢复该版本后重新预览。')
        if manifest['version'] != preview['base_version'] or hashlib.sha256(data).hexdigest() != preview['source_hash']:
            raise ValueError('数据源版本已变化，请重新预览；当前提交尚未保存。')
        record = normalize_record(cfg, preview['record'], rows, headers)
        if record != preview['record']:
            raise ValueError('确认内容与预览不一致，请重新预览。')

        def write_candidate(path):
            with path.open('x', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(original)
                writer.writerow(record)
        receipt = publish(cfg, write_candidate, preview['submission_id'], record['resident_id'], manifest['version'])
        return dict(receipt=receipt, active=receipt, already_applied=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['initialize', 'status'])
    parser.add_argument('--config', type=Path, default=config_path())
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
        print(json.dumps(initialize(cfg) if args.action == 'initialize' else current(cfg),
                         ensure_ascii=False, indent=2))
    except (OSError, ValueError, PublicationError) as exc:
        parser.exit(1, str(exc) + '\n')
