"""Server-side file authorization. Local demo identity is not production authentication."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path


def fingerprint(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


@dataclass(frozen=True)
class Context:
    tenant: str
    report: str
    path: str
    fingerprint: str

    @property
    def identity(self):
        return (self.tenant, self.report, self.fingerprint)


def authorize(tenant, selected, registry):
    selected = Path(selected).resolve(strict=True)
    for report, entry in registry.items():
        if entry['tenant'] == tenant and Path(entry['path']).resolve(strict=True) == selected:
            actual = fingerprint(selected)
            if entry.get('sha256') and entry['sha256'] != actual:
                raise ValueError('Report integrity check failed.')
            return Context(tenant, report, str(selected), actual)
    raise ValueError('Agent access is disabled for this report. Select a registered report.')


def event_source(context):
    """Resolve only the selected report's snapshot; the worker also checks its DB source hash."""
    database = Path(context.path).resolve()
    manifest_path = database.parent / 'manifest.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('db_sha256') != context.fingerprint:
            raise ValueError('Monthly activity source does not match the selected report.')
        raw = (database.parent / 'raw.csv').resolve()
        if raw.parent != database.parent or not raw.is_file():
            raise ValueError('The selected report has no intact local raw snapshot for monthly activity.')
        return {'path': str(raw)}
    # Legacy reports can use a server-configured seed only when the worker verifies
    # it is byte-identical to run_metadata.input_sha256. Never use a newer raw version.
    import report_versions as versions
    try:
        cfg = versions.load_config()
        raw = Path(cfg['source_csv']).resolve(strict=True)
    except (OSError, ValueError, KeyError):
        raise ValueError('Monthly activity needs the raw snapshot matching this report; no verified source is configured.') from None
    return {'path': str(raw)}


def local_context(root, selected):
    """Config is trusted server-side. Never derive tenant from model/session text."""
    root = Path(root).resolve()
    explicit = os.environ.get('HARBOURVIEW_AGENT_CONFIG')
    if explicit:
        settings = json.loads(Path(explicit).read_text(encoding='utf-8'))
        tenant, registry = settings['demo_tenant'], settings['reports']
        # Explicit entries must be absolute, to avoid CWD-dependent authorization.
        if any(not Path(e['path']).is_absolute() for e in registry.values()):
            raise ValueError('Registered report paths must be absolute.')
    else:
        tenant = 'harbourview-local-demo'
        registry = {}
        legacy = root / 'database' / 'harbourview.duckdb'
        if legacy.is_file():
            registry['legacy'] = dict(tenant=tenant, path=str(legacy))
        import report_versions as versions
        try:
            cfg = versions.load_config()
            manifest = versions.current(cfg)
            if manifest:
                _, active = versions.active_paths(cfg, manifest)
                registry[manifest['version']] = dict(tenant=tenant, path=str(active), sha256=manifest['db_sha256'])
        except (OSError, ValueError, KeyError):
            pass
    return authorize(tenant, selected, registry)
