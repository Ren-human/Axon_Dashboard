"""Self-contained report composed exclusively of executed evidence objects."""
from datetime import datetime, timezone
from html import escape
import json
import pandas as pd
from .catalog import METRICS, VERSION
from .chart_builder import build


def render_report(title, sections, source):
    failures = [item for item in sections if item.get('error')]
    status = 'partial' if failures else 'complete'
    timestamp = datetime.now(timezone.utc).isoformat()
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>' + escape(title) + '</title>',
             '<style>body{font:16px system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#153044}table{border-collapse:collapse;max-width:100%;display:block;overflow:auto}th,td{border:1px solid #cbd5e1;padding:8px;text-align:left}section{margin:36px 0}small{color:#526475}.warning{background:#fff2cf;padding:16px}pre{white-space:pre-wrap}</style>',
             '<h1>' + escape(title) + '</h1>',
             '<p>Status: ' + status + ' · Generated UTC: ' + timestamp + '</p>',
             '<h2>Scope and provenance</h2><pre>' + escape(json.dumps(source, ensure_ascii=False, indent=2)) + '</pre>']
    markdown = ['# ' + title, '', 'Status: ' + status, '', json.dumps(source, ensure_ascii=False), '']
    if failures:
        parts.append('<p class="warning">Partial report: unavailable sections are identified below. No cross-section conclusion is asserted.</p>')
    included_js = False
    for section in sections:
        label = METRICS[section['metric']]['label']
        parts.append('<section><h2>' + escape(label) + '</h2>')
        markdown.extend(['## ' + label, ''])
        if section.get('error'):
            parts.append('<p class="warning">Unavailable: validation or query failed. No figures reported.</p></section>')
            markdown.extend(['Unavailable: validation or query failed.', ''])
            continue
        frame = pd.DataFrame(section['rows'], columns=section['columns'])
        parts.extend(['<p>Evidence: ' + escape(section['evidence_id']) + '</p>',
                      '<p>Unit: ' + escape(section['unit']) + '</p>', frame.to_html(index=False, escape=True, na_rep='N/A')])
        for name in ('summary', 'detail'):
            if name in section:
                extra = section[name]
                extra_frame = pd.DataFrame(extra['rows'], columns=extra['columns'])
                parts.extend(['<h3>' + name.title() + '</h3><p>Evidence: ' + escape(extra['evidence_id']) + '</p>',
                              '<p>Unit: ' + escape(extra['unit']) + '</p>', extra_frame.to_html(index=False, escape=True, na_rep='N/A')])
                markdown.extend([name.title() + ' · Evidence: ' + extra['evidence_id'], '', '```csv',
                                 extra_frame.to_csv(index=False).strip(), '```', ''])
        fig = build(section)
        if fig is not None:
            parts.append(fig.to_html(full_html=False, include_plotlyjs=True if not included_js else False))
            included_js = True
        parts.extend(['<p>' + escape(section['note']) + '</p>',
                      '<details><summary>Validated specification</summary><pre>' +
                      escape(json.dumps(section['spec'], ensure_ascii=False, indent=2)) + '</pre></details></section>'])
        markdown.extend(['Evidence: ' + section['evidence_id'], '', 'Unit: ' + section['unit'], '',
                         '```csv', frame.to_csv(index=False).strip(), '```', '', section['note'], ''])
    parts.append('<footer>Catalog ' + VERSION + ' · Descriptive aggregates only. No resident records or verified causal conclusions.</footer></html>')
    return dict(title=title, status=status, sections=sections, source=source,
                generated_at=timestamp, html='\n'.join(parts), markdown='\n'.join(markdown))
