"""Wrap page.html (the published artifact source) into a standalone page:
reports/ued-bringup-steps.html. usage: python build.py"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
page = (HERE / 'page.html').read_text()
head_end = page.index('</style>') + len('</style>')
html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, '
        'viewport-fit=cover">\n' + page[:head_end] + '\n</head>\n<body>\n'
        + page[head_end:].lstrip('\n') + '</body>\n</html>\n')
out = HERE.parents[1] / 'ued-bringup-steps.html'
out.write_text(html)
print('wrote', out, len(html), 'bytes')
