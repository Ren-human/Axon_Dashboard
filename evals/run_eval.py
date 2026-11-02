"""Offline parsing regression; numerical and authorization tests live in tests/test_agent.py."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent.parser import parse


def main():
    os.environ['HARBOURVIEW_AGENT_MODE'] = 'rules'
    failures, total = [], 0
    for line in Path(__file__).with_name('questions.jsonl').read_text(encoding='utf-8').splitlines():
        case = json.loads(line)
        total += 1
        try:
            actual = parse(case['question'])
        except ValueError:
            actual = {'action':'error'}
        passed = actual['action'] == case['action']
        for field in ('intent','metric','view'):
            if field in case:
                passed = passed and actual.get('spec',{}).get(field) == case[field]
        if not passed:
            failures.append(case['id'])
    print(json.dumps({'total':total,'passed':total-len(failures),'failed_ids':failures}))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
